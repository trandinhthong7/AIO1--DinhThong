# W3-D5 Submission - Trần Đình Thông

## Môi trường kiểm thử

Em đã chạy self-test để kiểm tra đủ 6 safety path, sau đó khởi động Docker stack thật và chạy scenario latency trên `ronki-payment-svc`. Evidence thật được lưu trong `audit_log-real.jsonl`; `self-test.log` và `audit_log.jsonl` giữ evidence cho các stress path deterministic.

## Scenario 1 - Action succeeds

- Alert: `HighLatency`, service `payment-svc`
- Flow quan sát: `ALERT_DETECTED` -> `DECIDE_RUNBOOK` -> `BLAST_RADIUS_OK` -> `DRY_RUN_PASS` -> `ACTION_EXECUTED` -> `VERIFY_PASS` -> `ACTION_SUCCESS`
- Result: pass

Trong Docker run thật, fault đưa p99 lên khoảng `992.50ms`. Runbook restart xóa fault marker, restart container, rồi verify đo ba mẫu healthy liên tiếp `248.18ms`, `248.15ms`, `248.17ms`; cuối cùng log `ACTION_SUCCESS`. Runbook dry-run thực trả `[DRY-RUN] would execute: docker restart ronki-payment-svc`.

## Scenario 2 - Verify fails và rollback

- Alert: `InstanceDown`, service `checkout-svc`
- Flow quan sát: action execute thành công, `VERIFY_FAIL`, `ROLLBACK_TRIGGERED`, `ROLLBACK_EXECUTED`, `ROLLBACK_VERIFY_PASS`
- Docker evidence: `2026-06-18T10:10:38Z VERIFY_FAIL`, ngay sau đó có `ROLLBACK_TRIGGERED`; `10:10:45Z ROLLBACK_EXECUTED`.
- Result: pass trên Docker thật với `config.failure-test.yaml`.

Điểm em bổ sung so với minimum requirement là verify lại rollback. Như vậy orchestrator không đánh đồng “script rollback exit 0” với “service thật sự recovered”.

## Scenario 3 - Circuit breaker

- Setup: 3 service test liên tiếp có action success nhưng post-action verify fail
- Quan sát: 3 lần `ROLLBACK_TRIGGERED`, sau lần thứ ba có `CIRCUIT_BREAKER_HALT`
- Docker evidence: ba service `checkout-svc`, `inventory-svc`, `payment-svc` lần lượt verify fail. Tại `2026-06-18T10:14:19Z`, log có `CIRCUIT_BREAKER_HALT`, `consecutive_failures=3`, `threshold=3`.
- Final state: automation ngừng act và chỉ log `CIRCUIT_BREAKER_HALT` ở các poll sau.
- Result: pass trên Docker thật.

Circuit breaker không tăng counter khi decision validation fail, chỉ tăng sau action/verify/transaction failure.

## Scenario 4 - Transactional rollback

- Step A và B: `TRANSACTIONAL_STEP_COMPLETE`
- Step C: `TRANSACTIONAL_STEP_FAIL`
- Rollback order: `--rollback-b`, sau đó `--rollback-a`
- Event count: `TRANSACTIONAL_ROLLBACK_STEP` đúng 2 lần
- Result: pass

Docker evidence thật: `10:16:11Z TRANSACTIONAL_STEP_FAIL`, sau đó `TRANSACTIONAL_ROLLBACK_STEP` chạy `rollback-b` tại `10:16:15Z` và `rollback-a` tại `10:16:17Z`. Không có `ACTION_SUCCESS` cho transactional deploy bị fail.

## Scenario 5 - Concurrent alerts

- Payment và inventory cùng bắt đầu dry-run trong cùng một giây.
- Hai service khác nhau không block nhau và đều kết thúc `ACTION_SUCCESS`.
- Alert payment thứ hai trong lúc lock đang giữ tạo đúng một `SERVICE_LOCK_BUSY`.
- Result: pass

Docker evidence thật: ba `ALERT_DETECTED` xuất hiện cùng timestamp `10:17:00Z`; hai `DRY_RUN_PASS` của payment và inventory cách nhau khoảng 5ms. Payment alert thứ hai bị từ chối bởi `SERVICE_LOCK_BUSY`.

## Scenario 6 - Hallucination defense

- Alert: `TestHallucination`
- Bad runbook: `runbooks/nonexistent_runbook.sh`
- Event: `DECISION_VALIDATION_FAILED`, action `escalate_no_auto_action`
- Không có subprocess/runbook execution cho quyết định invalid.
- Result: pass

Docker evidence thật: `10:18:09Z ALERT_DETECTED` được theo ngay bởi `DECISION_VALIDATION_FAILED`; không có `RUNBOOK_EXEC` sau quyết định này.

## Tổng kết

- Required scenarios passed in offline safety self-test: `3/3`
- Stress scenarios passed in offline safety self-test: `3/3`
- Runbook dry-run scripts passed: `4/4`
- Python compile check: pass
- Real Docker chaos scenarios 1-3: pass
- Stress scenarios 4-6: pass bằng Docker/Alertmanager thật và deterministic safety self-test
- Real logs: `audit_log-real.jsonl` (scenario 1) và `audit_log-real-failures.jsonl` (scenario 2-3)
- Stress log: `audit_log-real-stress.jsonl` (scenario 4-6)
