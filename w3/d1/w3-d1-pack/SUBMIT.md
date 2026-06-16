# W3-D1 Submission — Trần Đình Thông

## 3 thứ em học được

1. Em học được rằng SLI nên đo từ phía user và phải proportional với user pain. CPU hay memory có ích cho dashboard capacity, nhưng không nên dùng làm SLI chính.
2. Em hiểu rõ hơn cách error budget biến SLO thành con số vận hành được. Ví dụ API SLO `99.9%` với `20737800` request/tháng cho phép khoảng `20737` fail/tháng, tương đương `43` phút ở traffic baseline.
3. Em học được vì sao MWMBR tốt hơn single-window alert: static baseline fire `22` lần với `19` false positive, còn rule MWMBR của em chỉ fire `3` lần và không có false positive.

## 1 thứ vẫn chưa rõ

Em vẫn chưa hoàn toàn chắc cách chọn SLO target khi baseline có cả incident trong dữ liệu. API availability quan sát theo fail rate là khoảng `99.6512%`, nhưng em vẫn chọn mục tiêu `99.9%` vì muốn dùng SLO như mục tiêu cải thiện reliability, không chỉ phản ánh hiện trạng.

## 1 trade-off trong SLO decision của em mà em không chắc

Trade-off em chưa chắc nhất là tune threshold Tier1 từ `14.4` xuống `5` và Tier2 từ `6` xuống `4`. Kết quả validation tốt hơn về MTTD (`0s`) và vẫn giữ noise reduction `86.4%`, nhưng threshold thấp hơn default có thể nhạy hơn nếu traffic production thay đổi hoặc fail pattern không giống synthetic data.

## Validation report

- noise_reduction_pct: 86.4%
- mttd_delta_s: 0s
- false_negative: 0
- verdict: pass