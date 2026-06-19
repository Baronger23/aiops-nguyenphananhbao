# W3-D3 Submission — Nguyen Phan Anh Bao

## Outage chosen
- ID: 3
- Name: Cloudflare WAF Regex (2019-07-02)
- Why this one: Quan sát cách một lỗi phần mềm (như evil regex) có thể gây quá tải CPU hệ thống lập tức trên diện rộng và cách thức phát hiện mà không cần dừng container.
- Failure mode: regex

## 3 bài học rút ra từ sự cố này
1.  **Thiếu cơ chế kiểm soát Blast Radius:** Deploy cấu hình toàn cầu đồng loạt (global deployment) mà không qua các giai đoạn canary hay blue-green là một mối nguy hiểm cực lớn, biến một lỗi cấu hình đơn lẻ thành sự cố sập mạng toàn cầu chỉ trong vài giây.
2.  **Scraper Timeout làm mù hệ thống giám sát:** Sự cố CPU saturation 100% làm treo tiến trình và chặn đứng khả năng phản hồi truy vấn của Prometheus scraper (Scrape Timeout). Điều này làm cho hệ thống AIOps chỉ đo các chỉ số HTTP bị mất dữ liệu và lầm tưởng hệ thống bình thường.
3.  **Tầm quan trọng của Regex Timeout & Static Analysis:** Trên các luồng xử lý hot-path (như kiểm tra bảo mật WAF cho mọi request), bắt buộc phải cấu hình giới hạn thời gian chạy regex tối đa (regex execution timeout) hoặc sử dụng các công cụ phân tích tĩnh trong CI để loại bỏ regex có nested quantifiers có nguy cơ catastrophic backtracking.

## 1 khía cạnh pipeline vẫn bỏ sót nếu sự cố xảy ra trong thực tế
- **Pattern:** Catastrophic backtracking xảy ra sâu bên trong một service ứng dụng cụ thể (không phải ở Gateway) và chỉ ảnh hưởng đến một vài request đặc thù chứa adversarial input, gây cạn kiệt connection pool cục bộ của service đó.
- **Why miss:** Pipeline hiện tại chưa tích hợp giám sát chi tiết trạng thái connection pool của từng container và chưa đo thời gian chạy của riêng luồng xử lý regex ở tầng code (app-level profiling), do đó chỉ phát hiện trễ tăng lên chung ở Gateway mà không biết nguyên nhân gốc là do regex backtrack cục bộ.
- **Mitigation idea:** Tích hợp APM (Application Performance Monitoring) tự động profile các thread chạy lâu hơn 50ms và xuất thông tin stack trace của thread bị nghẽn trực tiếp về pipeline để phân tích RCA.

## 1 quyết định trong ADR chưa mang lại sự chắc chắn hoàn toàn
Quyết định lựa chọn mô hình học máy **Isolation Forest** trong bộ Ensemble chưa mang lại sự chắc chắn hoàn toàn. Dù mô hình phát hiện bất thường đa biến tốt, việc bảo trì mô hình này trong thực tế rất phức tạp. Khi hệ thống production thay đổi tải liên tục (ví dụ: ngày lễ, flash sale), dữ liệu baseline cũ sẽ không còn đúng, dễ sinh ra cảnh báo giả dồn dập hoặc bỏ sót lỗi thực sự nếu không có cơ chế tự động dán nhãn và tái huấn luyện (retraining) cực kỳ chuẩn xác.

## Kết luận từ mô hình chi phí (Cost model verdict) cho hệ thống
- **ROI:** 3.2
- **Payback:** 0.3125 tháng (khoảng 9.4 ngày)
- **Verdict:** worth_it
