# Chaos Engineering Report — Trần Đình Thông

## 1. Setup

- Stack version + commit hash: starter pack only, repo commit `064bf52`
- Pipeline version + commit hash: simulated AIOps pipeline outcome, repo commit `064bf52`
- Baseline window: `2026-06-16T10:55:00+00:00` -> `2026-06-16T11:00:00+00:00`
- Total experiments run: 10
- Important note: pack W3-D2 does not ship the 10-service docker stack or FastAPI AIOps pipeline. Em implemented the real command dispatcher in `chaos_runner.py`, then used `--mode simulate` so the catalog, scoring, probe evidence, and report workflow can run locally without pretending a missing stack exists.

## 2. Results table

==== Chaos Run ====
Total: 10
Detected: 8/10
RCA correct: 6/8
False alarms in baseline windows: 0
Precision: 1.00
Recall: 0.80
MTTD p50: 43s, p95: 64s

Per-experiment:

| # | name | detected | mttd | rca_service | rca_correct |
|---|---|---|---|---|---|
| 1 | payment_latency | Y | 24s | payment-svc | Y |
| 2 | payment_packet_loss | Y | 38s | payment-svc | Y |
| 3 | inventory_pod_kill | Y | 52s | inventory-svc | Y |
| 4 | gateway_cpu_saturation | Y | 46s | api-gateway | Y |
| 5 | payment_db_memory_fill | Y | 64s | payment-db | Y |
| 6 | auth_clock_skew | N | - | - | N |
| 7 | log_collector_disk_fill | N | - | - | N |
| 8 | frontend_gateway_partition | Y | 31s | api-gateway | Y |
| 9 | dns_lookup_latency | Y | 89s | api-gateway | N |
| 10 | checkout_retry_storm | Y | 41s | checkout-svc | N |

Gaps identified:

- 6: detector silent for `auth_clock_skew` -> detector threshold or missing auth/JWT signal
- 7: detector silent for `log_collector_disk_fill` -> missing meta-monitoring signal
- 9: RCA picked `api-gateway` -> topology/causal RCA weakness
- 10: RCA picked `checkout-svc` -> retry-storm RCA picked symptom carrier

## 3. Detailed per-experiment analysis

### 1. payment_latency

Hypothesis: khi inject 500ms +/- 100ms delay vào `payment-svc` trong 60s, steady-state có thể giảm nhưng detector phải fire latency anomaly trong 30s và RCA phải chọn `payment-svc`. Observed trong run mô phỏng: detected `Y`, MTTD `24s`, RCA service `payment-svc`, RCA correct `Y`. Kết quả match expected vì latency fault nằm đúng ở dependency trực tiếp của checkout, alert đến trước ngưỡng 30s, và RCA không bị kéo sang checkout hay api-gateway. Với baseline simulated, probe pass-rate trước run là `100%`, checkout p99 baseline khoảng `244ms`, nên spike 500ms là đủ lớn để vượt noise floor. Đây là case pipeline xử lý tốt nhất: signal rõ, topology đơn giản, root tạo anomaly trước downstream.

### 2. payment_packet_loss

Hypothesis: inject packet loss 30% vào `payment-svc` trong 60s sẽ tăng timeout và error-rate, detector fire trong 45s, RCA chọn `payment-svc`. Observed: detected `Y`, MTTD `38s`, RCA service `payment-svc`, RCA correct `Y`. Em xem case này pass vì MTTD nằm dưới ngưỡng hypothesis và RCA không nhầm sang `checkout-svc`, dù checkout là nơi user thấy lỗi. Evidence chính là fault class `network_loss`, alert service là `payment-svc`, và root service trùng ground truth. So với latency injection, packet loss mất thêm thời gian vì error-rate cần tích lũy qua vài scrape/window mới vượt threshold. Đây là hành vi hợp lý của detector dựa trên burn/error-rate thay vì alert từng request lỗi đơn lẻ.

### 3. inventory_pod_kill

Hypothesis: killing một `inventory-svc` container mỗi 60s sẽ gây availability anomaly ngắn, detector fire trong 60s và RCA pick `inventory-svc`. Observed: detected `Y`, MTTD `52s`, RCA service `inventory-svc`, RCA correct `Y`. Kết quả match expected nhưng sát ngưỡng hơn hai case đầu, vì pod kill có thể được restart nhanh và symptom bị làm mượt bởi retry hoặc load balancing. Điểm tích cực là RCA vẫn chọn đúng inventory thay vì `api-gateway`, nghĩa là topology signal hoặc restart_count được dùng đúng. Với blast radius một instance, đây là experiment tốt để kiểm tra detector có bỏ qua “short availability dip” hay không. Nếu chạy thật, em sẽ nhìn thêm restart_count và available_replicas để xác nhận anomaly không chỉ đến từ probe.

### 4. gateway_cpu_saturation

Hypothesis: stress CPU `api-gateway` lên 90% trong 90s sẽ tạo latency cascade trên downstream, detector fire trong 60s và RCA chọn `api-gateway` như upstream bottleneck chung. Observed: detected `Y`, MTTD `46s`, RCA service `api-gateway`, RCA correct `Y`. Case này match expected và khá quan trọng vì downstream có thể cùng chậm, khiến RCA naive chọn service ồn nhất. Việc chọn `api-gateway` cho thấy pipeline simulated đang ưu tiên common ancestor trong topology thay vì chỉ đếm số alert. Baseline gateway p99 simulated là `151ms`, nên CPU 90% đủ để tạo p99 latency deviation rõ. Nếu chạy stack thật, em sẽ verify thêm saturation metric không được dùng làm SLI page trực tiếp, mà chỉ làm evidence cho RCA.

### 5. payment_db_memory_fill

Hypothesis: fill memory `payment-db` lên 95% trong 90s sẽ tăng query latency và connection pool wait, detector fire trong 60s, RCA chọn `payment-db`. Observed: detected `Y`, MTTD `64s`, RCA service `payment-db`, RCA correct `Y`. Experiment này hơi chậm hơn hypothesis 4s, nhưng vẫn được tính detected và RCA đúng trong scoreboard. Lý do có thể là memory pressure cần thời gian để biến thành query latency hoặc pool wait, nhất là nếu cache vẫn còn warm. Điểm đáng chú ý là RCA không dừng ở `payment-svc`; nó đi sâu được tới stateful dependency. Với production-like stack, em sẽ thêm metric `connection_pool_wait_seconds` và DB slow query count để làm evidence link rõ hơn giữa memory fill và lỗi checkout.

### 6. auth_clock_skew

Hypothesis: skew clock `auth-svc` +60s trong 60s sẽ tạo JWT hoặc certificate validation failures, detector fire trong 60s và RCA chọn `auth-svc`. Observed: detected `N`, MTTD `-`, RCA service `-`, RCA correct `N`. Đây là false negative đầu tiên. Em nghi pipeline thiếu detector chuyên cho auth/JWT/cert hoặc threshold error-rate quá cao nên signal không vượt noise floor, nhất là nếu health endpoint không đi qua auth flow đầy đủ. Failure mode này giống “detector miss”: metric user-visible có thể chưa giảm mạnh, nhưng auth-specific logs đã có lỗi. Fix nên là thêm blackbox probe cho authenticated checkout path và detector trên `jwt_validation_error_rate`, thay vì chỉ dựa vào generic 5xx hoặc latency.

### 7. log_collector_disk_fill

Hypothesis: fill disk `log-collector` lên 95% trong 120s sẽ tăng log ingestion lag, meta-monitoring fire trong 90s, user probe có thể vẫn healthy, RCA chọn `log-collector`. Observed: detected `N`, MTTD `-`, RCA service `-`, RCA correct `N`. Đây là gap quan trọng vì nó không nhất thiết ảnh hưởng user path ngay, nhưng làm mù AIOps pipeline. Nếu log ingestion lag tăng mà không alert, pipeline có monitoring dependency loop: khi observability path hỏng, detector lại mất input để tự báo. Em xem đây là missing meta-monitoring hơn là lỗi RCA. Fix cụ thể là tách observability SLO riêng, alert trên ingestion lag, dropped log count, disk usage, và có external heartbeat từ log pipeline.

### 8. frontend_gateway_partition

Hypothesis: partition frontend với `api-gateway` trong 30s sẽ tạo all-downstream timeout, detector fire trong 45s, RCA chọn edge hoặc `api-gateway`. Observed: detected `Y`, MTTD `31s`, RCA service `api-gateway`, RCA correct `Y` theo ground truth trong `experiments.yaml`. Kết quả match expected vì partition ở edge làm probe thấy lỗi trực tiếp, nên detection nhanh hơn nhiều fault nội bộ. RCA chọn `api-gateway` là chấp nhận được trong lab vì đó là boundary service nhận timeout từ frontend. Nếu chạy thật, em muốn RCA evidence ghi rõ đây là network edge fault, không phải gateway process bug. Nếu không phân biệt được hai loại này, remediation có thể đi sai hướng: restart gateway thay vì kiểm tra network policy/iptables/LB route.

### 9. dns_lookup_latency

Hypothesis: thêm DNS lookup latency 2s trong 90s sẽ gây intermittent timeout, detector fire trong 90s, topology-aware RCA chọn `dns-resolver`. Observed: detected `Y`, MTTD `89s`, RCA service `api-gateway`, RCA correct `N`. Detection vừa kịp nhưng RCA sai. Đây là pattern “RCA wrong root”: symptom rõ nhất xuất hiện ở `api-gateway` vì gateway gọi nhiều downstream và chịu timeout, nhưng root thật là dependency nền `dns-resolver`. Pipeline cần dependency model có DNS như shared infrastructure node, không chỉ service-to-service HTTP graph. Fix nên là thêm DNS lookup p99/error metric vào evidence, dùng topology với shared dependency, và yêu cầu RCA chứng minh causal order: DNS latency tăng trước, gateway timeout tăng sau.

### 10. checkout_retry_storm

Hypothesis: inject 20% HTTP 500 ở `checkout-svc` trong 90s sẽ tạo retry storm tới upstream; pipeline không được chọn `checkout-svc` làm root mà phải chọn upstream có queue/saturation evidence. Observed: detected `Y`, MTTD `41s`, RCA service `checkout-svc`, RCA correct `N`. Detection tốt nhưng RCA fail đúng mục tiêu negative test. Đây là failure mode “pick service ồn nhất”: checkout phát nhiều lỗi nhất nên bị chọn root, dù lỗi retry storm cần phân biệt symptom carrier với dependency gây queue. Fix là RCA phải kết hợp retry_count, queue_depth, topology direction, và temporal lag. Nếu checkout error xuất hiện sau upstream saturation, root không nên là checkout. LLM RCA cũng cần evidence citation bắt buộc để tránh trả lời tự tin nhưng sai.

## 4. Gap analysis — top 3 pipeline weakness

### Gap 1: Missing auth-specific detector

- Symptom: experiment 6 `auth_clock_skew` bị miss hoàn toàn, detected `N`.
- Likely cause in pipeline: detector chỉ nhìn generic latency/error-rate hoặc unauthenticated health endpoint, nên JWT/cert failure không vượt threshold.
- Recommended fix: thêm synthetic probe cho authenticated flow, detector trên `jwt_validation_error_rate`, `token_expired_unexpected_count`, cert validation error, và segmented alert theo auth path. Đây là counter cho failure mode detector miss dưới noise floor.

### Gap 2: No meta-monitoring for observability path

- Symptom: experiment 7 `log_collector_disk_fill` bị miss dù expected là log ingestion lag.
- Likely cause in pipeline: monitoring dependency loop, pipeline không tự quan sát log ingestion lag/dropped log/disk usage của chính log path.
- Recommended fix: tách observability stack khỏi monitored services, thêm SLO cho ingestion freshness, blackbox heartbeat từ log-collector tới pipeline, và alert ticket/page khi lag vượt ngưỡng. Đây là counter trực tiếp cho monitoring dependency loop.

### Gap 3: RCA is not causal enough for shared infra and retry storms

- Symptom: experiment 9 chọn `api-gateway` thay vì `dns-resolver`; experiment 10 chọn `checkout-svc` dù ground truth là `NOT checkout-svc`.
- Likely cause in pipeline: RCA ưu tiên service ồn nhất hoặc common endpoint, chưa dùng shared dependency graph và temporal-causal evidence.
- Recommended fix: thêm topology node cho DNS/cache/log infra, dùng lag analysis để xem metric nào drift trước, và bắt RCA trả evidence link theo dạng metric anomaly + topology distance + timestamp order.

## 5. Hypothesis cho gap chưa khẳng định

Em muốn chạy thêm một experiment để phân biệt “detector miss” và “probe sai coverage” ở auth: gọi một endpoint bắt buộc login bằng synthetic probe ngoài cluster, sau đó skew clock `auth-svc` +60s. Nếu authenticated probe fail nhưng pipeline vẫn silent, lỗi nằm ở detector auth signal. Nếu probe vẫn pass, lab health endpoint chưa đại diện user journey thật.
