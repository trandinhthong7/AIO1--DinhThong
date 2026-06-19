# ADR-001: Use audit-aware causal RCA for operational incidents

## Status

Accepted

## Context

Trong AWS S3 reproduction, pipeline phát hiện ba service down trong 2 giây nhưng RCA chọn `billing` với confidence `0.42`. Đây là symptom đầu tiên theo tie-break, không phải root cause. Root thực tế là unscoped maintenance command xảy ra trước ba state transition, nhưng pipeline không ingest operator/change audit signal. Quyết định kiến trúc cần cải thiện RCA cho cascading và multi-service incidents mà vẫn giữ output có thể audit.

## Decision

Em chọn RCA kết hợp ba signal theo thứ tự: signed change/audit event, topology + blast-radius relation, và first-drift temporal order; alert volume chỉ dùng làm tie-breaker. RCA chỉ được trả confidence cao khi evidence chứa ít nhất một causal event và một affected dependency. Khi audit signal vắng mặt, output phải ghi `insufficient_causal_evidence` và confidence không vượt `0.50`.

## Alternatives considered

### 1. Count-based hoặc first-alert ranking

- **Pros:** đơn giản, chi phí thấp, trả kết quả nhanh và không cần topology.
- **Cons:** retry storm làm downstream ồn hơn root; simultaneous stop khiến tie-break chọn billing như reproduction.
- **Decision:** rejected làm primary RCA, chỉ giữ làm fallback.

### 2. Topology-only graph ranking

- **Pros:** hiểu upstream/downstream và common dependency; tốt hơn count-only cho cascade.
- **Cons:** graph không chứng minh một operator command đã gây lỗi; topology stale có thể tạo root sai.
- **Decision:** giữ như một signal nhưng không dùng độc lập.

### 3. LLM-only RCA

- **Pros:** tổng hợp log tự nhiên tốt và có thể giải thích giả thuyết.
- **Cons:** có thể tạo root cause plausible nhưng không grounded; chi phí và latency biến động.
- **Decision:** rejected làm decision authority; LLM chỉ diễn giải evidence đã được causal engine chọn.

### 4. Audit-aware causal RCA

- **Pros:** nối trực tiếp change event với affected target, dùng temporal order và topology để kiểm chứng.
- **Cons:** cần signed audit schema, clock alignment và change-event retention.
- **Decision:** accepted.

## Consequences

- **Positive:** reproduction sẽ xác định root là `unscoped_compose_stop`, không phải billing.
- **Positive:** confidence trở nên grounded và có evidence chain dùng được trong postmortem.
- **Trade-off:** cần tích hợp maintenance CLI, deploy system và IAM audit source.
- **Trade-off:** correlation phức tạp hơn và cần giữ timestamp lệch không quá 2 giây.
- **Risk:** audit source outage có thể làm RCA degrade; mitigation là confidence cap và explicit fallback status.
- **Risk:** topology stale có thể mở rộng sai impact; mitigation là versioned topology và freshness alert.
