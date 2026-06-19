# Submission Reflection

## Incident khó chẩn đoán nhất

Incident khó nhất đối với em là I-5, liên quan đến quá trình xoay vòng
chứng chỉ mTLS và sai lệch đồng hồ. Ban đầu, em nghi ngờ bản deploy
`payment-svc` lúc 05:30 vì đây là thay đổi gần thời điểm lỗi nhất. Tuy
nhiên, trường `extra` trong log TLS cho thấy chứng chỉ có
`not_before=06:00:15Z`, trong khi thời gian hiện tại của validator chỉ
là `05:59:48Z`. Giá trị `delta_seconds=-27` chứng minh nguyên nhân thực
sự là clock skew, không phải nội dung chứng chỉ hay bản deploy.

## Giả thuyết em từng cân nhắc

Ở I-3, em từng cho rằng đây là một retry storm giống I-1 vì cả hai cùng
phát alert `PaymentConnPoolSaturated`. Sau khi kiểm tra
`fx_api_5xx_per_min.csv`, em thấy số lỗi của `fx-api` vẫn bằng 0 và
`payment_retries_per_min` không tăng. Log `rds-orders` lại ghi nhận truy
vấn trên bảng `transactions` với `uses_index=false` ngay sau khi feature
flag được bật. Bằng chứng này khiến em loại bỏ giả thuyết retry storm.

## File hữu ích nhất

File hữu ích nhất với em là `deploy_log.json`. File này giúp liên kết
chính xác các thay đổi cấu hình với telemetry, đặc biệt là feature flag
ở I-3 và thông báo đổi IP của vendor ở I-4. Nó cũng giúp em loại bỏ các
thay đổi chỉ gần nhau về thời gian nhưng không nằm trên causal path.

## Blind spot của data pack

Data pack chưa có metric NTP drift theo host và chưa cung cấp đầy đủ
metric theo từng availability zone. Nếu có
`node_time_drift_seconds`, I-5 sẽ được nhận diện nhanh hơn. Tương tự,
metric `payment_error_rate` có nhãn `az` và kết quả DNS theo từng AZ sẽ
giúp phát hiện ngay sự phân kỳ của AZ-c trong I-4.
