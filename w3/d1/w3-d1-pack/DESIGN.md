# W3-D1 Design

## 1. SLI choice cho frontend

Với frontend, em chọn SLI `frontend_page_experience_ok = dom_ready_ms < 3000 AND js_error == false AND network_error == false` trên dữ liệu RUM. Baseline cho thấy frontend có `518400` event trong 3 ngày, tương đương `172800` event/ngày; `success_rate` hiện tại là `0.9861`, `fail_rate` là `1.3897%`, và p99 DOM ready là `1430ms`. Em chọn metric tổng hợp này vì nó gần với trải nghiệm người dùng thật: trang phải load xong trong ngưỡng hợp lý và không có lỗi JS/network. Nếu chỉ chọn page load time hoặc DOM ready thì sẽ bỏ sót trường hợp trang load nhanh nhưng JS lỗi. Nếu chỉ chọn JS error rate thì sẽ bỏ sót network error và trang chậm. Nếu chỉ chọn network error thì quá hẹp, vì baseline có `4682` JS error, `2433` network error, nhưng chỉ `131` event chậm hơn 3000ms. Vì vậy metric tổng hợp phản ánh user pain tốt hơn từng signal riêng lẻ.

## 2. SLO target cho API

Em chọn API SLO target `99.9%` trong 30 ngày. API là tầng trung tâm của service map, frontend phụ thuộc API và API phụ thuộc DB, nên lỗi API lan trực tiếp lên trải nghiệm mua hàng. Baseline có `2073780` API request trong 3 ngày, `691260` request/ngày, `7234` request fail do `5xx` hoặc `429`, fail rate `0.3488%`. Nếu nhìn availability không tính `4xx` của user, service đang khoảng `99.6512%`, nhưng dữ liệu có cả incident, nên em xem `99.9%` là mục tiêu vận hành để kéo reliability lên. Nếu chọn `99%`, monthly budget sẽ quá rộng, khoảng `207378` fail/tháng, dễ bỏ qua incident nhỏ. Nếu chọn `99.99%`, budget chỉ khoảng `2073` fail/tháng, thấp hơn cả fail count 3 ngày hiện tại nên không thực tế nếu chưa đầu tư multi-AZ, automated runbook và on-call mạnh. Với `99.9%`, budget là `20737` fail/tháng, tương đương `43` phút ở traffic baseline.

## 3. Latency threshold p99

Em chọn latency threshold `500ms` cho API SLI phụ về latency, đồng thời dùng p99 làm số quan sát chính. Dữ liệu 3 ngày cho thấy API latency p50 `45ms`, p90 `86ms`, p95 `104ms`, p99 `156ms`, p99.9 `394ms`, và max `2553ms`. Phân phối theo bucket cũng khá rõ: `94.04%` request dưới `100ms`, `98.82%` dưới `150ms`, `99.57%` dưới `200ms`, `99.94%` dưới `500ms`; chỉ `0.05%` nằm trong `500-1000ms` và `0.01%` trên `1000ms`. Nếu cắt ở `200ms`, SLI sẽ nhạy với một phần tail nhỏ nhưng vẫn có nguy cơ page vì dao động không gây đau lớn. Nếu cắt ở `1s`, ngưỡng quá rộng và bỏ qua tail latency đáng chú ý. Vì p99 hiện là `156ms`, em chọn `500ms` để bắt request chậm thật sự nhưng vẫn có buffer hợp lý cho spike ngắn.

## 4. 4xx exclusion

Em loại `4xx` khỏi error count, trừ `429`, vì đa số `4xx` là lỗi do request của client, bot, hoặc user nhập sai, không phải hệ thống không phục vụ được. Trong access log, các mã `400`, `401`, `403`, `404` lần lượt có `10482`, `10435`, `10394`, `10401` event; nếu tính toàn bộ `4xx` vào lỗi hệ thống thì SLI API sẽ bị kéo xuống dù backend vẫn trả lời đúng theo contract. Em vẫn tính `429` là fail vì đó là hệ thống từ chối phục vụ user do rate limit hoặc capacity, và baseline có `1049` event `429`. Khi em kiểm tra theo endpoint, không có endpoint nào có rate `4xx > 5%`, nên chưa có bằng chứng một route cụ thể đang gây user pain do lỗi sản phẩm. Vì vậy công thức API availability của em là: good khi status không phải `5xx` và không phải `429`; `4xx` còn lại được xem là neutral/user-side.

## 5. MWMBR tuning

Em bắt đầu từ Google default: Tier1 `1h/5m` threshold `14.4`, Tier2 `6h/30m` threshold `6`, Tier3 `3d/6h` threshold `1`. Khi validate với dữ liệu pack, default đã giảm noise từ `22` lần fire của static baseline xuống `3`, FN `0`, nhưng mttd delta chạm `60s`. Vì đề yêu cầu mttd delta dưới `60s`, em tune page threshold xuống Tier1 `5` và Tier2 `4`, giữ đúng cặp window MWMBR và giữ Tier3 `1` dạng ticket. Kết quả cuối trong `validation_report.json`: static baseline `fired=22`, `tp=3`, `fp=19`, `fn=0`, `mttd_p50_s=0`; rule MWMBR của em `fired=3`, `tp=3`, `fp=0`, `fn=0`, `mttd_p50_s=0`. Noise reduction đạt `86.4%`, mttd delta `0s`, verdict `pass`. Trade-off là threshold thấp hơn default nên cần review định kỳ khi traffic thật thay đổi.
