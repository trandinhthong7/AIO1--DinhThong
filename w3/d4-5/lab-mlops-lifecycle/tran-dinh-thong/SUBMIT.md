# W3-D4 Submission - Trần Đình Thông

## 1. Drift threshold

Em chọn threshold `0.15` và đã validate trực tiếp trên data pack. Evidently trả drift score `1.0000`, với mean latency tăng từ `128.95ms` lên `162.37ms`, error rate gần gấp đôi và RPS tăng khoảng 30%. Threshold thấp hơn có thể bắt seasonality nhỏ thành drift thật, làm retrain quá thường xuyên. Vì vậy em dùng thêm approval gate và performance threshold để tránh promotion chỉ dựa trên một score.

## 2. Nếu v2 tệ hơn v1

V2 được đăng ký vào `staging`, chưa thay production ngay. Sau approval, `post_deploy_monitor` đánh giá precision trong 24 cycles; nếu precision dưới `0.65`, code gắn v2 vào `archived`, restore alias `production` về v1 và gọi `/reload`. Audit log lưu version bị demote, version restore, precision và cycle. Em đã test nhánh này bằng threshold fault-test `1.01`, rollback xảy ra ở cycle 1 và v1 được phục hồi.

## 3. Data drift và concept drift

Data drift là P(X) thay đổi, ví dụ latency/RPS/error-rate dịch chuyển sau campaign. Concept drift là P(Y|X) thay đổi, nghĩa là cùng feature nhưng quan hệ với anomaly label không còn giống trước. Evidently `DataDriftPreset` trong lab phát hiện data drift; nó không tự phát hiện concept drift. Vì vậy `drift_detector.py` có combined mode đánh giá thêm precision/recall trên data có nhãn; run thật cho precision v1 `0.3154` và recall `0.8020`.

## 4. Vì sao blue-green quan trọng

Thay file model trực tiếp làm mất rollback path và có thể tạo request lỗi trong lúc process đang đọc artifact. Blue-green giữ v1 production trong khi v2 ở staging, cho phép kiểm tra version, holdout và approval trước cutover. Swap chỉ đổi alias MLflow rồi reload model, nên không cần redeploy API. Nếu v2 degrade, alias quay lại v1 trong vài giây và audit trail vẫn giữ đủ version.

## 5. Nếu tự động hóa approval gate

Nếu bỏ human approval, em yêu cầu combined gate gồm drift score `>0.15`, v2 precision trên labeled validation không thấp hơn v1 quá 0.02, recall không thấp hơn 0.03, và tối thiểu 100 positive labels. Sau promotion, precision phải giữ `>=0.65` trong 24 cycles; vi phạm sẽ auto-rollback. Em không dùng F1 đơn lẻ vì payment incident có cost false negative và false positive khác nhau. Gate cũng phải kiểm tra latency serving p99 không tăng quá 20% so với v1.
