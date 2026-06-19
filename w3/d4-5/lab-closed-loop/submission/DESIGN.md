# Closed-Loop Design - Trần Đình Thông

## 1. Decision engine

Em chọn rule-based decision engine. Ba alert chính có mapping rõ: `HighLatency` và `InstanceDown` dùng restart, `HighErrorRate` dùng clear cache. Rule-based deterministic, dễ audit và phù hợp remediation có blast radius cao; đổi lại nó kém linh hoạt với alert mới. Em vẫn thêm `runbook_registry` để chống quyết định trỏ tới script không tồn tại. Self-test `TestHallucination` đã tạo `DECISION_VALIDATION_FAILED` và không có `RUNBOOK_EXEC` sau event đó.

## 2. Blast radius

Production config giới hạn `3` actions/phút trên toàn hệ thống và `5` restart/service/giờ. Ronki có 5 service, nên 3 actions/phút cho phép xử lý một cascade nhỏ nhưng không restart toàn stack cùng lúc. Giới hạn 5 restart/giờ ngăn restart loop trên một service bị lỗi cấu hình hoặc dependency. Khi vượt limit, orchestrator log `BLAST_RADIUS_EXCEEDED` và escalates thay vì tiếp tục act. Self-test dùng limit cao hơn tạm thời để chạy đủ scenario, còn config nộp bài vẫn giữ 3 và 5.

## 3. Verify

Verify dùng Prometheus query p99 latency và `up`. Action pass khi latency p99 `<500ms` và `up>=1` trong ít nhất `3` mẫu liên tiếp; polling mỗi `10s`, timeout `60s`. Ba mẫu liên tiếp giảm khả năng một scrape may mắn làm action được đánh dấu success. Nếu verify fail, rollback tự động chạy và chính rollback cũng được verify lại, tạo `ROLLBACK_VERIFY_PASS` hoặc `ROLLBACK_VERIFY_FAIL`. Baseline thật của payment-svc là p99 `195ms`, checkout `230ms`, nên 500ms có buffer nhưng vẫn thấp hơn fault inject 500ms cộng latency nền.

## 4. Circuit breaker reset

Circuit breaker mở sau `3` failure liên tiếp do action fail hoặc verify fail. Em chọn reset manual: operator phải kiểm tra dependency, audit log và nguyên nhân rollback trước khi restart orchestrator. Auto-reset theo timer có thể lặp lại cùng action phá hoại khi fault gốc chưa được sửa. Một success reset consecutive counter về 0 trước khi circuit mở. Self-test tạo 3 verify failure liên tiếp và log `CIRCUIT_BREAKER_HALT` cùng `CIRCUIT_STATE result=open`.

## Stress design

Transactional deploy lưu danh sách step hoàn thành và rollback theo thứ tự ngược; self-test làm step C fail, sau đó rollback B rồi A đúng 2 lần. Main loop dùng thread pool để hai service khác nhau chạy song song, nhưng mutex theo service khiến alert payment thứ hai nhận `SERVICE_LOCK_BUSY`. Mọi event có `ts`, `event_type`, `service`, `action`, `result` và có thể append vào `AUDIT_LOG_PATH`. Command được parse bằng `shlex`, nhưng executable phải nằm trong registry trước khi bất kỳ subprocess nào được tạo.
