# W3-D2 Submission — Trần Đình Thông

## 3 thứ em học được về AIOps pipeline của mình

1. Em học được rằng detect được fault chưa đủ; RCA cũng phải đúng causal chain. Run này detect `8/10`, nhưng RCA chỉ đúng `6/8` vì DNS latency và retry storm bị chọn sai root.
2. Em thấy synthetic probe rất quan trọng vì nó là steady-state signal từ góc nhìn user. Trong pack này probe evidence là simulated, nhưng workflow vẫn nhắc em không nên chỉ tin metric nội bộ.
3. Em học được rằng observability path cũng cần SLO riêng. `log_collector_disk_fill` bị miss cho thấy nếu log pipeline hỏng mà không có meta-monitoring, AIOps có thể bị mù đúng lúc cần nhất.

## 1 fault mà em mong pipeline catch nhưng nó miss

- Experiment: `auth_clock_skew`
- Why I expected detection: clock skew +60s ở `auth-svc` có thể làm JWT hoặc certificate validation fail, gây lỗi login/checkout.
- Why pipeline missed (hypothesis): detector có thể chỉ nhìn generic 5xx/latency hoặc health endpoint không đi qua authenticated flow, nên auth-specific error không đủ mạnh để vượt threshold.

## 1 trade-off trong design pipeline mà em muốn rethink

Em muốn rethink trade-off giữa RCA đơn giản theo “service ồn nhất” và RCA topology-causal. Cách đơn giản dễ implement và chạy nhanh, nhưng experiment `dns_lookup_latency` và `checkout_retry_storm` cho thấy nó dễ chọn sai root khi shared infrastructure hoặc retry storm làm downstream ồn hơn root thật.

## Scoreboard summary

- detected: 8/10
- rca_correct: 6/8
- mttd_p50: 43s
- false_alarms: 0
- verdict: pass