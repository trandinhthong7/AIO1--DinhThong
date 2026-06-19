# AIOps Mini-Platform Spec — Trần Đình Thông

## 1. Platform overview

Platform quan sát web/API/database stack, phát hiện anomaly, correlate alert, đề xuất RCA và cung cấp closed-loop remediation có guardrail. User chính là SRE/on-call và service owner. Scope hiện tại là local production-like stack; cloud deployment, security automation và autonomous high-risk database action chưa nằm trong scope.

## 2. SLO definition (from W3-D1)

| Service | SLI | SLO/30 ngày | Monthly budget |
|---|---|---:|---:|
| Frontend | DOM ready < 3000ms, không JS/network error | 99.0% | 51,840 failed RUM events, 432 phút equivalent |
| API | Status không phải 5xx/429 | 99.9% | 20,737 failed requests, 43 phút equivalent |
| DB | Query success và duration < 100ms | 99.95% | 863 failed queries, 21 phút equivalent |

API dùng MWMBR page tiers `1h/5m @ 5` và `6h/30m @ 4`; ticket tier `3d/6h @ 1`. Validation giảm noise `86.4%`, false negative `0`, MTTD delta `0s`.

## 3. Detection + Correlation + RCA stack (from W1+W2)

**Detection:** request/error/latency, RUM, DB và operational metrics được chuẩn hóa thành anomaly/availability events. SLO signal dùng MWMBR; drift hoặc leading indicator dùng statistical/ML detector.

**Correlation:** event được nhóm theo temporal window và service topology. Correlator phải giữ shared infrastructure như DNS, auth và observability path, không chỉ application HTTP edges.

**RCA:** theo [ADR-001](ADR.md), engine ưu tiên signed change event, topology relation và first-drift order. Alert count chỉ là tie-breaker; LLM không được tạo root nếu không có evidence.

## 4. Reliability validation (from W3-D2)

- Chaos experiments: `10`.
- Detected: `8/10`, recall `0.80`.
- RCA correct: `6/8` detected cases.
- MTTD p50: `43s`; false alarms: `0`.
- Steady-state signal: external synthetic probe cùng internal metrics.

Top gaps:

1. Auth clock skew bị miss do thiếu authenticated probe/JWT detector.
2. Log collector disk fill bị miss do thiếu meta-monitoring.
3. DNS latency và retry storm bị RCA chọn symptom carrier thay vì causal root.

Cadence đề xuất: weekly staging chaos, monthly production canary game day và quarterly destructive-command exercise.

## 5. Operational pattern (from W3-D3)

Outage reproduced: AWS S3 2017 operator typo/insufficient blast radius. Local run có 18 timeline events, MTTD `2s`, outage `8s`, full recovery `10s` sau inject. Pipeline detect đúng multi-service outage nhưng RCA chọn billing, chứng minh cần change-aware causal evidence. Postmortem dùng Google SRE blameless format; mọi action item có owner, due date và priority. Architecture decision được ghi tại ADR-001.

## 6. Cost model (from W3-D3)

Ronki-like e-commerce input:

- Services: `50`
- Incidents: `4/tháng`
- Average duration: `1.25h`
- Downtime cost: `$50,000/h`
- Expected MTTR reduction: `40%`
- AIOps cost: `$30,000/tháng`

Output:

- Monthly value: `$100,000`
- Monthly cost: `$30,000`
- ROI: `3.33`
- Payback: `0.30 tháng`
- Verdict: `worth_it`

Break-even ROI 1.0 xảy ra ở downtime cost `$15,000/h`; để đạt `worth_it` theo rule ROI > 1.5 cần downtime cost lớn hơn `$22,500/h`.

## 7. Open risks

| Risk | Severity | Mitigation |
|---|---|---|
| Pipeline thiếu signed operator/deploy audit event | Critical | Implement ADR-001 change-event schema |
| Auth-specific detector chưa có | High | Authenticated synthetic probe + JWT error SLO |
| Observability path có thể tự bị mù | Critical | Out-of-band heartbeat và independent monitoring plane |
| Topology stale làm RCA sai shared dependency | High | Versioned topology, freshness SLO, owner review |
| Automatic remediation có thể lặp action lỗi | High | Dry-run, blast radius, rollback verify, manual-reset circuit breaker |
