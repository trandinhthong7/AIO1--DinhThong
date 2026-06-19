# MLOps Lifecycle Design - Trần Đình Thông

## 1. Drift threshold

Em chọn dataset drift threshold `0.15`. Khi chạy `drifted.csv`, Evidently báo drift score `1.0000`, tức cả 3 feature `latency_p99`, `error_rate`, `rps` đều drift. Số liệu cũng cho thấy thay đổi lớn: latency mean từ `128.95ms` lên `162.37ms`, error rate từ `0.7913%` lên `1.4818%`, và RPS từ `468.17` lên `610.05`. Threshold 0.15 thấp hơn score thực tế rất xa nên bắt được campaign shift, nhưng vẫn yêu cầu ít nhất một phần đáng kể feature drift. Nếu đặt quá thấp, ví dụ 0.01, batch nhỏ hoặc seasonality bình thường có thể trigger retrain liên tục, tốn tài nguyên và tạo model churn.

## 2. Drift type

Lab chứa đồng thời data drift và performance/concept drift. `DataDriftPreset` phát hiện thay đổi P(X), thể hiện bằng drift score `1.0000`. Tuy nhiên nó không chứng minh P(Y|X) đã đổi, nên em chạy combined mode với labeled current data. Model v1 trên `drifted.csv` đạt precision `0.3154`, recall `0.8020`, thấp hơn performance threshold `0.70`; đây là tín hiệu performance degradation và là proxy thực tế cho concept drift. Với payment anomaly detection, combined mode phù hợp vì một “new normal” có thể làm feature thay đổi, còn rollout processor mới có thể thay đổi quan hệ giữa feature và incident.

## 3. Retrain trigger

Em dùng semi-automatic trigger: drift detector tự động tạo v2 và gắn alias `staging`, nhưng promotion cần người phê duyệt bằng prompt `[y/N]`. Người duyệt là ML engineer đang on-call cùng service owner của payment gateway; timeout vận hành đề xuất là 30 phút, hết thời gian thì mặc định từ chối. Em không chọn unconditional auto-promotion vì drift chỉ nói distribution thay đổi, không đảm bảo model mới tốt hơn. Em vẫn đề xuất cadence review hàng tuần để phát hiện dữ liệu thiếu nhãn hoặc detector drift bị hỏng, nhưng chỉ retrain khi combined gate hoặc policy review xác nhận nhu cầu.

## 4. Versioning và rollback

Em dùng cả immutable MLflow version number và movable aliases `production`, `staging`, `archived`. `serve.py` luôn load `models:/anomaly-detector@production`, nên cutover không cần đổi code hay thay file model trực tiếp. Trước promotion, orchestrator lưu version production cũ; nếu post-deploy precision dưới `0.65`, code gắn v2 vào `archived`, trỏ `production` về v1 và gọi `/reload`. Trong run test, v1 là version `1`, v2 là version `2`, và forced rollback đã restore v1 ở cycle 1. ML platform on-call được quyền rollback tự động theo policy; service owner có quyền rollback thủ công khi có user-impact evidence.

## 5. Combined drift mode

Combined mode là bắt buộc vì hai detector trả lời hai câu hỏi khác nhau. Data-only run báo score `1.0000`, nhưng không cho biết model còn dự đoán đúng hay không. Performance check cho số cụ thể: precision `0.3154`, recall `0.8020`; model bắt được nhiều anomaly nhưng tạo nhiều false positive. Ngược lại, nếu feature distribution gần baseline nhưng 25% label bị flip, data score có thể thấp trong khi precision giảm mạnh. Em trigger retrain khi data drift vượt 0.15 hoặc precision dưới 0.70, và log cả hai signal để người phê duyệt thấy bằng chứng.

## 6. Retrain data selection

Em dùng sliding window kết hợp baseline `4320` rows và current `1008` rows, tổng `5328` rows. Nếu chỉ train trên 7 ngày drifted, model dễ quên old regime; nếu chỉ giữ baseline, model không học được traffic mới. Cách concat giữ cả hai phân phối và vẫn cho current chiếm khoảng 18.9% training set. Holdout file của pack có `500` row nhưng toàn bộ `anomaly_label=0`, nên precision và recall đều `0.0000` cho cả v1/v2 và không đủ để so chất lượng anomaly detection. Em vẫn in đúng acceptance line, đồng thời ghi rõ cần một holdout có cả positive và negative label trước khi dùng làm promotion gate production.

## 7. Post-deploy rollback

Default gate trong code là precision `< 0.65` qua tối đa 24 polling cycles. Với `post_deploy_eval.csv`, v2 đạt precision/recall `1.0000`, nên default policy giữ v2. Để test nhánh rollback, em chạy threshold test-only `1.01`; cycle 1 trigger audit event `auto_rollback_v2_to_v1` với `demoted_version=2`, `restored_version=1`, `trigger_precision=1.0`. Tham số này chỉ phục vụ fault-path validation, không phải cấu hình production. Production giữ 0.65 vì thấp hơn baseline 0.91 đáng kể nhưng tránh rollback do dao động nhỏ trên batch 200 rows.
