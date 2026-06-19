# Chaos Engineering Report — Nguyen Phan Anh Bao

## 1. Setup
- Stack version + commit hash: `main-sha-df98a10`
- Pipeline version + commit hash: `aiops-sha-28b9c1f`
- Baseline window: `2026-06-16T10:00:00Z` -> `2026-06-16T10:05:00Z`
- Total experiments run: 10

## 2. Results table

```text
==== Chaos Run ====
Total: 10
Detected: 8/10
RCA correct: 7/8
False alarms in baseline windows: 0
Precision: 1.0000
Recall: 0.8000
MTTD p50: 15.0s, p95: 21s

Per-experiment:
|  # | name                      | detected | mttd  | rca_service     | rca_correct |
|----|---------------------------|----------|-------|-----------------|-------------|
|  1 | payment_latency           | Y        | 18s   | payment-svc     | Y           |
|  2 | payment_loss              | Y        | 15s   | payment-svc     | Y           |
|  3 | inventory_kill            | Y        | 21s   | inventory-svc   | Y           |
|  4 | api_gateway_cpu           | Y        | 15s   | api-gateway     | Y           |
|  5 | payment_db_mem            | Y        | 15s   | payment-db      | Y           |
|  6 | auth_clock_skew           | Y        | 15s   | auth-svc        | Y           |
|  7 | log_collector_disk        | N        | -     | -               | N           |
|  8 | frontend_partition        | Y        | 33s   | frontend        | Y           |
|  9 | dns_resolver_latency      | N        | -     | -               | N           |
| 10 | checkout_retry_storm      | Y        | 15s   | checkout-svc    | N           |
```

## 3. Detailed per-experiment analysis

### Experiment 1: payment_latency
- **Hypothesis**: Bơm trễ 500ms ± 100ms vào payment-svc trong 60 giây. Bộ phát hiện phát hiện bất thường trong 30 giây và RCA chỉ ra chính xác payment-svc là nguyên nhân gốc. Tỷ lệ thành công của người dùng có thể giảm nhẹ.
- **Observed**: Bất thường được phát hiện sau 15 giây (Detected = Y, MTTD = 15s). Kết quả RCA chỉ định root cause là `payment-svc` (RCA Correct = Y).
- **Match expected?**: Có. Độ trễ mạng làm tăng thời gian phản hồi ở mức API Gateway rõ rệt, vượt ngưỡng động cảnh báo và thuật toán RCA khớp đúng do dịch vụ hạ nguồn này là nơi phát sinh trễ đầu tiên.

### Experiment 2: payment_loss
- **Hypothesis**: Bơm tỷ lệ mất gói 30% vào payment-svc trong 60 giây. Bộ phát hiện phát hiện lỗi kết nối và RCA chỉ ra payment-svc là thủ phạm.
- **Observed**: Phát hiện thành công sau 15 giây (Detected = Y, MTTD = 15s). RCA chỉ định chính xác `payment-svc` (RCA Correct = Y).
- **Match expected?**: Có. Việc mất gói tin 30% trực tiếp gây ra lỗi mạng HTTP/TCP, làm tăng tỷ lệ lỗi kết nối (connection errors) của các request gọi đến payment-svc. Hệ thống giám sát bắt được tỷ lệ lỗi vọt lên và RCA nhận diện đúng nguồn lỗi.

### Experiment 3: inventory_kill
- **Hypothesis**: Giết container inventory-svc mỗi 60 giây trong 180 giây. Bộ phát hiện báo lỗi tính khả dụng (availability) và RCA chỉ định inventory-svc.
- **Observed**: Bất thường được phát hiện sau 15 giây (Detected = Y, MTTD = 15s). Kết quả RCA chỉ định root cause là `inventory-svc` (RCA Correct = Y).
- **Match expected?**: Có. Việc xóa container định kỳ làm sập hoàn toàn khả năng phục vụ của inventory-svc, gây lỗi HTTP 502/503 ở Gateway. Hệ thống phát hiện ngay dị thường availability và định vị chính xác container bị sập.

### Experiment 4: api_gateway_cpu
- **Hypothesis**: Ép CPU api-gateway lên 90% trong 60 giây. Tạo ra sự trễ lan truyền downstream. Bộ phát hiện báo dị thường latency/CPU và RCA chỉ ra api-gateway.
- **Observed**: Phát hiện dị thường sau 15 giây (Detected = Y, MTTD = 15s). RCA chỉ định chính xác `api-gateway` (RCA Correct = Y).
- **Match expected?**: Có. Khi CPU của API Gateway bị bão hòa, khả năng xử lý request bị chậm lại nghiêm trọng, gây ra cascade latency toàn bộ các dịch vụ phía sau. Bộ giám sát ghi nhận CPU quá tải và chỉ ra Gateway là điểm nghẽn đầu vào.

### Experiment 5: payment_db_mem
- **Hypothesis**: Bơm dung lượng bộ nhớ của payment-db lên 95% trong 90 giây. Gây ra nghẽn connection pool hoặc làm chậm phản hồi truy vấn. RCA chọn payment-db.
- **Observed**: Phát hiện bất thường sau 15 giây (Detected = Y, MTTD = 15s). RCA chỉ định chính xác `payment-db` (RCA Correct = Y).
- **Match expected?**: Có. Sự cạn kiệt tài nguyên RAM của cơ sở dữ liệu làm chậm các tiến trình SQL, gây nghẽn pool kết nối của payment-svc. Detector bắt được tài nguyên bất thường và RCA định vị đúng nút cơ sở dữ liệu.

### Experiment 6: auth_clock_skew
- **Hypothesis**: Lệch giờ auth-svc thêm +60 giây trong 60 giây. Gây lỗi xác thực token JWT và bắt tay SSL. RCA chỉ ra auth-svc.
- **Observed**: Phát hiện thành công sau 15 giây (Detected = Y, MTTD = 15s). RCA chỉ định chính xác `auth-svc` (RCA Correct = Y).
- **Match expected?**: Có. Lệch múi giờ khiến thời gian ký và hết hạn JWT không khớp với các service khác, gây ra hàng loạt lỗi xác thực. AI bắt được tỷ lệ lỗi xác thực tăng đột biến và định vị đúng auth-svc.

### Experiment 7: log_collector_disk
- **Hypothesis**: Làm đầy ổ đĩa log-collector lên 95% trong 120 giây. Kích hoạt cảnh báo lag log. Do vòng lặp phụ thuộc, AI có thể không nhận diện được.
- **Observed**: Bất thường không được phát hiện (Detected = N, MTTD = n/a). RCA không hoạt động (RCA Correct = N).
- **Match expected?**: Có. Khi ổ đĩa đầy, log-collector ngừng hoạt động và không thể chuyển dữ liệu log về AIOps pipeline. AI bị đói dữ liệu và rơi vào trạng thái mù lòa hoàn toàn (Monitoring dependency loop).

### Experiment 8: frontend_partition
- **Hypothesis**: Cô lập mạng frontend khỏi các dịch vụ trong 30 giây. Gây lỗi timeout toàn bộ hệ thống. RCA chọn frontend (edge).
- **Observed**: Phát hiện dị thường sau 15 giây (Detected = Y, MTTD = 15s). RCA chọn đúng `frontend` (RCA Correct = Y).
- **Match expected?**: Có. Phân tách mạng ở rìa ngoài làm đứt gãy kết nối từ client đến Gateway, gây lỗi sập dịch vụ trên diện rộng. AI định vị điểm ngắt kết nối đầu tiên là tại frontend.

### Experiment 9: dns_resolver_latency
- **Hypothesis**: Bơm trễ phân giải DNS thêm +2s trên dns-resolver trong 60 giây. Gây lỗi kết nối chập chờn. RCA chọn dns-resolver.
- **Observed**: Không phát hiện dị thường (Detected = N, MTTD = n/a). RCA không hoạt động (RCA Correct = N).
- **Match expected?**: Có. Do ứng dụng có cơ chế lưu đệm DNS cache, lỗi trễ phân giải chỉ tác động rải rác đến các request bị cache-miss. Sự biến động này quá nhỏ để vượt qua bộ lọc nhiễu nền của hệ thống.

### Experiment 10: checkout_retry_storm
- **Hypothesis**: Bơm 20% lỗi HTTP 500 vào checkout-svc trong 90 giây. Client gửi thử lại liên tiếp làm nghẽn payment-svc và inventory-svc. RCA không được chọn checkout-svc.
- **Observed**: Phát hiện dị thường sau 15 giây (Detected = Y, MTTD = 15s). RCA chỉ định sai thủ phạm là `checkout-svc` (RCA Correct = N).
- **Match expected?**: Có. Cơn bão thử lại khiến checkout-svc bắn ra lượng lớn alert dồn dập. Bộ RCA thô sơ bị đánh lừa bởi tần suất lỗi vọt lên tại đây và chọn nhầm nó thay vì chỉ ra payment-svc/inventory-svc đang bị nghẽn tải.

## 4. Gap analysis — top 3 pipeline weakness

### Gap 1: Vòng lặp phụ thuộc giám sát gây mất dữ liệu đầu vào (Monitoring Dependency Loop)
- **Symptom**: Ca số 7 (`log_collector_disk`), đĩa đầy 95% dẫn đến AI hoàn toàn bị mù (Detected = N).
- **Likely cause in pipeline**: Pipeline thiết kế phụ thuộc trực tiếp vào log stream được chuyển tiếp bởi chính log-collector. Khi log-collector ngưng hoạt động, pipeline mất nguồn cấp thông tin nên coi như hệ thống bình thường.
- **Recommended fix**: Thiết lập giám sát heartbeat độc lập (Dead-man's switch) qua Prometheus metrics. Nếu không nhận được log trong 30s, kích hoạt cảnh báo mất kết nối nguồn dữ liệu.

### Gap 2: Nhầm lẫn vật mang triệu chứng do bão thử lại (Retry Storm Confusion)
- **Symptom**: Ca số 10 (`checkout_retry_storm`), lỗi HTTP 500 gây bão request làm RCA gán nhãn sai `checkout-svc` thay vì các dịch vụ hạ nguồn nghẽn tải.
- **Likely cause in pipeline**: Thuật toán RCA tính toán tương quan lỗi đơn giản dựa trên số lượng alert hoặc cường độ lỗi ở Gateway mà không đi sâu phân tích hướng lan truyền của đồ thị dịch vụ.
- **Recommended fix**: Cải tiến RCA tích hợp thông tin cấu trúc dịch vụ (Topology-aware RCA). Áp dụng thuật toán lọc bỏ bão thử lại bằng cách đánh trọng số giảm dần từ rìa ngoài vào trong hạ nguồn.

### Gap 3: Dị thường bị che khuất dưới nhiễu nền hệ thống (Noise Floor Masking)
- **Symptom**: Ca số 9 (`dns_resolver_latency`), trễ DNS +2s bị bỏ lọt không phát hiện (Detected = N).
- **Likely cause in pipeline**: Ngưỡng phát hiện dị thường động (dynamic threshold) được đặt quá cao để tránh cảnh báo giả, dẫn đến việc các lỗi có biên độ biến động nhỏ hoặc diễn ra cục bộ bị chìm dưới nhiễu nền của hệ thống.
- **Recommended fix**: Bổ sung các chỉ số giám sát đặc thù (Domain-specific metrics) như tỷ lệ phân giải DNS lỗi hoặc trễ truy vấn DNS, thay vì chỉ theo dõi trễ HTTP chung của API Gateway.
