# DESIGN.md — Ronki Closed-Loop Orchestrator

## 1. Decision engine: Rule-based hay LLM-based?

**Chọn: Rule-based.**

Lý do:
- Stack Ronki có 3 loại alert được định nghĩa rõ ràng (`HighLatency`, `HighErrorRate`, `InstanceDown`) và mỗi loại ánh xạ 1-1 với một runbook đã được ops team kiểm chứng. Trong môi trường này, rule-based cho **latency quyết định < 1ms** và **deterministic (hoàn toàn xác định)** — cùng một alert luôn trigger cùng một runbook.
- Tránh chi phí mạng và độ trễ từ 200–800ms khi gọi API của LLM, đồng thời triệt tiêu hoàn toàn rủi ro ảo tưởng (hallucination) của LLM trong hệ thống production tự động.

Mở rộng:
Nếu sau này hệ thống mở rộng lên hàng chục loại alert phức tạp hơn với mô tả tự nhiên, chúng ta có thể tích hợp mô hình LLM với một ngưỡng tin cậy tối thiểu `confidence >= 0.6` và xây dựng cơ chế fallback về Rule-based khi LLM không thể đưa ra quyết định hợp lệ.

---

## 2. Blast-radius config

Cấu hình giới hạn Blast-Radius:
```yaml
blast_radius:
  max_actions_per_minute: 3
  max_restarts_per_service_per_hour: 5
```

Lý do chọn giá trị:
- `max_actions_per_minute: 3`: Hệ thống Ronki có 5 dịch vụ. Nếu xảy ra hiện tượng lỗi dây chuyền (cascade failure), việc khống chế tối đa 3 hành động khắc phục trong 1 phút giúp ngăn việc bộ điều phối khởi động lại đồng loạt tất cả dịch vụ cùng lúc (gây thâm hụt tài nguyên nghiêm trọng hoặc nghẽn database).
- `max_restarts_per_service_per_hour: 5`: Nếu một dịch vụ bị lỗi và phải khởi động lại quá 5 lần trong một giờ nhưng vẫn tiếp tục phát sinh cảnh báo, điều này chứng tỏ lỗi nghiêm trọng không thể tự phục hồi (ví dụ: lỗi OOM liên tục, sai cấu hình môi trường, hoặc cơ sở dữ liệu bị hỏng). Việc tiếp tục khởi động lại là vô ích và có hại — hệ thống cần tạm dừng và leo thang cảnh báo cho kỹ sư vận hành xử lý thủ công.

---

## 3. Verify step

**Metric kiểm tra:** 
1. p99 latency (ms)
2. up (1/0)

**Cấu hình ngưỡng (Threshold):**
- `latency_p99_max_ms: 500`: Dựa vào baseline.json, p99 latency của dịch vụ chậm nhất (`checkout-svc`) lúc hoạt động bình thường là 230ms. Đặt ngưỡng 500ms giúp phát hiện hiệu quả tình trạng nghẽn cổ chai mà không gây cảnh báo giả (false negative).
- `up_required: 1`: Đảm bảo container đang chạy và phản hồi thành công.
- `verify_timeout_seconds: 60`: Quá trình khởi động lại container thường mất từ 5-10 giây, và Prometheus cần thêm khoảng 15-20 giây để cập nhật lại chỉ số mới qua các scrape cycle (chu kỳ 10 giây). Ngưỡng 60 giây đủ cho 3 chu kỳ cào dữ liệu của Prometheus sau khi container khởi động lại.
- `verify_poll_interval_seconds: 10`: Trùng khớp với khoảng thời gian cào metric của Prometheus.
- `verify_min_samples: 3`: Yêu cầu phải có ít nhất 3 mẫu kiểm tra liên tiếp đạt yêu cầu thì mới xác nhận khắc phục thành công. Điều này triệt tiêu các trường hợp thành công giả lập thời gian ngắn (false positive).

---

## 4. Circuit breaker reset

**Reset mode: manual (bằng tay).**

Lý do:
Khi Circuit Breaker chuyển sang trạng thái `OPEN` (mở cầu dao) do 3 lần lỗi liên tiếp (lỗi chạy runbook hoặc lỗi xác minh verify), hệ thống đang ở trong tình trạng bất thường rất nghiêm trọng.
Nếu chúng ta cấu hình tự động reset sau một thời gian, bộ điều phối có nguy cơ rơi vào một vòng lặp vô hạn (infinite loop) khởi động lại liên tục, gây quá tải kết nối cơ sở dữ liệu (connection exhaustion) hoặc làm trầm trọng thêm sự cố.

Do đó, bắt buộc kỹ sư vận hành phải can thiệp thủ công, kiểm tra log hệ thống để tìm ra nguyên nhân gốc rễ và xử lý xong. Sau đó reset bộ điều phối bằng cách khởi động lại tiến trình Python:
```bash
Ctrl+C
uv run python closed_loop.py --config config.yaml
```

---

## 5. Mutex strategy (Stress 2 — concurrent alert race)

**Thiết kế:**
Sử dụng một `threading.Lock` cho mỗi dịch vụ cụ thể. Khi có alert đến, bộ điều phối gọi `acquire(blocking=False)` để lấy khóa. Nếu một dịch vụ đang chạy runbook, khóa sẽ bận và alert trùng lặp mới gửi đến cho dịch vụ đó sẽ bị bỏ qua (ghi log `SERVICE_LOCK_BUSY`), thay vì phải xếp hàng đợi.
Hai dịch vụ khác nhau sở hữu hai khóa mutex độc lập nên hoàn toàn có thể thực thi runbook song song mà không làm nghẽn tiến trình của nhau.

Lý do sử dụng `blocking=False`: Trong khắc phục sự cố khép kín, một runbook đang xử lý là một hành động đang được thực hiện. Alert trùng lặp gửi đến trong vòng vài giây tiếp theo là do độ trễ cập nhật chỉ số, không phải sự cố mới. Việc xếp hàng và chạy lại runbook sau khi khóa giải phóng sẽ khiến hệ thống restart dịch vụ 2 lần liên tục — rất nguy hiểm và không cần thiết.

---

## 6. Rollback chain ordering (Stress 1 — multi-step transactional deploy)

**Thiết kế:**
Hàm `run_transactional_steps` thực hiện tuần tự các bước A $\rightarrow$ B $\rightarrow$ C và ghi lại danh sách các bước đã hoàn thành thành công.
Nếu bước C gặp lỗi, bộ điều phối sẽ kích hoạt chuỗi rollback và duyệt danh sách các bước đã thực hiện theo thứ tự đảo ngược (LIFO) bằng `reversed()` — nghĩa là thực hiện rollback-B trước rồi mới đến rollback-A. Các bước chưa từng chạy (như C) sẽ không bị rollback.

Lý do:
Thiết kế này tuân theo đúng nguyên lý LIFO (Last-In, First-Out) giống như Transaction Rollback trong database. Bước A (ví dụ: rút traffic) tạo tiền đề cho bước B (apply config). Nếu ta phục hồi traffic (rollback A) trước khi khôi phục config cũ (rollback B), dịch vụ có thể phải nhận traffic trong trạng thái config không nhất quán, gây sập hệ thống. Do đó, việc dọn dẹp (teardown) phải đi ngược lại hoàn toàn với quy trình thiết lập (setup).

---

## 7. Decision validation policy (Stress 3 — LLM hallucination defense)

**Thiết kế:**
Trước khi thực hiện chạy thử (dry-run), hàm `validate_runbook` sẽ tách lấy tên base script từ quyết định của engine (ví dụ: `runbooks/multi_step_deploy.sh`) và đối chiếu xem nó có nằm trong whitelist `runbook_registry` cấu hình tại `config.yaml` hay không.
Nếu không hợp lệ, hệ thống lập tức log `DECISION_VALIDATION_FAILED` và dừng xử lý ngay lập tức mà không sinh bất kỳ tiến trình con nào.

Lý do:
Khi sử dụng LLM hoặc người dùng vô tình sửa cấu hình sai lệch, quyết định đưa ra có thể trỏ tới một đường dẫn không tồn tại hoặc độc hại (ví dụ: `runbooks/nonexistent.sh`). Nếu không validate, hệ thống chạy subprocess sẽ bị lỗi exit non-zero, khiến chỉ số Circuit Breaker bị tăng lên vô lý và có thể mở cầu dao oan uổng. Validation trước giúp giữ cho log sạch sẽ và ngăn chặn triệt để các rủi ro bảo mật hệ thống.
