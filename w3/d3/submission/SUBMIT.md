# W3-D3 Submission — Trần Đình Thông

## Outage chosen

- **ID:** 1
- **Name:** AWS S3 us-east-1, 2017-02-28
- **Why this one:** Em chọn outage này vì một command nhỏ có thể tạo blast radius lớn dù từng container hoạt động đúng thiết kế. Pattern này liên kết trực tiếp với closed-loop safety: dry-run, explicit target, approval và max-action guard quan trọng không kém detector.
- **Failure mode:** operator action without guardrail.

## 3 thứ tôi học từ outage này

1. Em học được detection nhanh không đồng nghĩa RCA đúng. Pipeline detect sau 2 giây nhưng chọn billing với confidence 0.42, trong khi cause là unscoped command.
2. Em thấy audit/change event phải là observability signal hạng nhất. Chỉ metric và container state không thể phân biệt maintenance action với infrastructure crash.
3. Em hiểu blast radius cần được enforce trước execution. Confirmation sau khi command đã resolve target set là quá muộn; policy phải kiểm target count, criticality và approval trước side effect.

## 1 thứ pipeline của tôi sẽ vẫn miss nếu outage này xảy ra real

- **Pattern:** operator action làm nhiều service biến mất đồng thời.
- **Why miss:** pipeline chỉ ingest service state, không ingest actor role, command hash, intended scope, resolved target set hoặc approval ID.
- **Mitigation idea:** emit signed change events và correlate chúng với first-drift time + topology theo ADR-001. Khi evidence thiếu, confidence phải bị cap dưới 0.50.

## 1 quyết định trong ADR mà tôi không hoàn toàn chắc

Em chưa hoàn toàn chắc cách đặt trọng số giữa change event và topology. Change event gần thời điểm incident là evidence mạnh nhưng có thể chỉ trùng hợp, còn topology có thể stale. Em chọn rule-based evidence ordering trước, sau đó mới tune weights bằng chaos catalog. Production cần đánh giá precision RCA trên nhiều incident class trước khi cho engine tự trigger remediation.

## Cost model verdict cho stack của tôi

- **Monthly value:** `$100,000`
- **Monthly cost:** `$30,000`
- **ROI:** `3.33`
- **Payback:** `0.30 tháng`
- **Verdict:** `worth_it`

Downtime cost `$50,000/h` phù hợp mid-tier e-commerce và scenario Ronki mất khoảng 1,000 order trong 15 phút. Nếu downtime cost giảm dưới `$15,000/h`, cùng incident profile này không còn break-even.
