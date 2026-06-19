# Postmortem: Unscoped maintenance command stops metadata subsystems

**Status:** complete  
**Date:** 2026-06-18  
**Authors:** Trần Đình Thông  
**Severity:** SEV1  
**Duration:** 8 seconds of service unavailability (18:12:55 UTC → 18:13:03 UTC)

## Summary

Trong reproduction mô phỏng AWS S3 2017, một maintenance command dự kiến chỉ tác động billing nhưng interface không bắt buộc target scope. Command đã dừng đồng thời billing, index và placement; hai subsystem metadata quan trọng không thể phục vụ object lookup hoặc placement. Pipeline phát hiện ba instance unavailable, và recovery khởi động lại toàn bộ service sau 8 giây.

## Impact

- **Users affected:** 100% request mô phỏng cần index hoặc placement trong cửa sổ 8 giây.
- **Services affected:** billing, index, placement.
- **Revenue impact:** khoảng `$111.11` nếu áp downtime cost `$50,000/giờ`.
- **SLO budget consumed:** khoảng `0.31%` của API monthly downtime budget 43 phút.
- **External communication:** không cần status-page update vì đây là local reproduction; production policy sẽ yêu cầu update cho SEV1.
- **Duration:** 18:12:55 UTC → 18:13:03 UTC, tổng 8 giây.

## Timeline (UTC)

| Time | Event |
|---|---|
| 18:12:50 | Timeline capture bắt đầu. |
| 18:12:50 | Billing được xác nhận ở trạng thái `running`. |
| 18:12:50 | Index được xác nhận ở trạng thái `running`. |
| 18:12:50 | Placement được xác nhận ở trạng thái `running`. |
| 18:12:53 | Fault injection bắt đầu với intended target là billing. |
| 18:12:55 | Unscoped compose stop hoàn tất với return code 0. |
| 18:12:55 | Billing chuyển từ `running` sang `exited`. |
| 18:12:55 | Index chuyển từ `running` sang `exited`. |
| 18:12:55 | Placement chuyển từ `running` sang `exited`. |
| 18:12:56 | Pipeline phát ba alert `InstanceUnavailable`; index và placement có severity critical. |
| 18:13:02 | Recovery bắt đầu bằng scoped compose start. |
| 18:13:03 | Billing, index và placement trở lại `running`; full recovery hoàn tất. |

## Root cause

Root cause là maintenance interface cho phép destructive command chạy ở project scope mà không yêu cầu explicit target, preview, approval hoặc blast-radius limit. Một sai lệch nhỏ giữa intended scope và executed scope vì vậy có thể tác động mọi subsystem trong compose project.

## Causal tree

```text
Metadata outage
├── Unscoped destructive command
│   ├── Target argument không bắt buộc
│   └── Không có dry-run/preview
├── Shared blast-radius boundary
│   ├── Billing, index, placement cùng compose project
│   └── Không có max-target guard
└── Incomplete diagnosis
    ├── Pipeline chỉ thấy container state
    └── Không ingest operator/change audit event
```

## Contributing factors

1. Billing, index và placement nằm chung operational scope dù criticality khác nhau.
2. Command không có allowlist hoặc giới hạn số resource tối đa được stop trong một lần.
3. Pipeline không ingest change event nên chỉ correlate ba symptom đồng thời.
4. RCA tie-break theo thứ tự service và chọn billing, thay vì xác định root là maintenance command.

## Detection

- **How detected:** pipeline poll Docker state mỗi giây và phát `InstanceUnavailable`.
- **MTTD:** 2 giây từ inject start 18:12:53 đến alert fire timestamp 18:12:55; alert được timeline quan sát lúc 18:12:56.
- **Could it be earlier:** pre-execution policy có thể chặn command trước khi side effect xảy ra.
- **Pipeline gap 1:** RCA chọn `billing` với confidence `0.42`; expected root là unscoped operator command, không phải một service.
- **Pipeline gap 2:** không có operator-command audit signal nên pipeline không phân biệt maintenance action với infrastructure-wide crash.
- **Pipeline gap 3:** topology chưa mô tả index và placement là dependency bắt buộc của object operations.

## Response

- **First responder action:** xác nhận cả ba container `exited`, đối chiếu inject output, sau đó chạy scoped recovery script.
- **Time to mitigate:** 9 giây từ inject start đến recovery start.
- **Time to fully resolve:** 10 giây từ inject start; user-visible unavailable window là 8 giây.

### What went well

- Pipeline phát hiện đủ ba service và giữ index/placement ở critical severity.
- MTTD 2 giây, thấp hơn target 30 giây.
- Recovery script scoped rõ compose file và đưa cả ba container về `running`.

### What went poorly

- RCA output không xác định được change event và đưa ra root service sai.
- Destructive operation không có dry-run, confirmation hay blast-radius policy.
- Alert cluster không kèm dependency impact, nên incident commander phải suy luận thủ công.

### Where we got lucky

- Reproduction không có persistent data nên stop/start không gây data loss.
- Recovery path đã biết trước và image không cần rebuild.

## Action items

| Item | Owner | Due | Priority |
|---|---|---|---|
| Bắt buộc `--target` và từ chối target rỗng cho maintenance CLI | Platform Engineering | 2026-06-26 | P0 |
| Thêm dry-run diff và two-person approval khi action chạm hơn 1 critical subsystem | SRE Lead | 2026-07-03 | P0 |
| Emit signed change event gồm actor role, command hash, target set và approval ID | Developer Platform | 2026-07-10 | P1 |
| Ingest change event vào RCA và ưu tiên cause xảy ra trước symptom | AIOps Team | 2026-07-17 | P1 |
| Tách index/placement khỏi billing blast-radius boundary | Storage Team | 2026-07-31 | P1 |
| Thêm game-day test cho unscoped destructive command mỗi quý | Reliability Program | 2026-08-07 | P2 |
