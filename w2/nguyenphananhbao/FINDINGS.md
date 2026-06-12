# FINDINGS.md — Câu hỏi phản biện sự cố

Các câu trả lời dưới đây tham chiếu đến số liệu và hành vi thực tế từ quá trình chạy 8 sự cố thử nghiệm (E01 - E08).

---

### 1. Hàm tương đồng (similarity function) nào được lựa chọn cho Layer 2, và tại sao?

Lựa chọn được đưa ra là **Hàm tương đồng Jaccard có điều kiện & Độ lệch chuẩn hóa kết hợp chuẩn hóa trọng số động (Conditional Weighted Jaccard & Normalized Deviation Similarity with Dynamic Weight Normalization)**.

#### Các phương án khác từng được cân nhắc:
- **Dense Embeddings (ví dụ: SentenceTransformers)**: Phương án nhúng các dòng log và metric thành các vector 384 chiều đã được xem xét. Tuy nhiên, với tập dữ liệu lịch sử nhỏ (chỉ 29 sự cố), các mô hình nhúng rất dễ bị quá khớp (overfit) và gặp khó khăn trong việc biểu diễn các mối quan hệ cấu trúc đồ thị (như đường đi của trace).
- **Hàm tương đồng Cosine với Trọng số cố định (Fixed-Weight Cosine)**: Cách tiếp cận này sẽ phạt nặng các sự cố bị thiếu một vài thành phần thông tin. Ví dụ, trong sự cố `E03` (Memory Leak), live incident có thông tin trace bị lỗi, nhưng sự cố lịch sử `INC-2025-08-02` lại hoàn toàn trống phần `trace_signatures`. Nếu dùng trọng số cố định, độ tương đồng trace sẽ bị tính là `0.0`, kéo điểm tương đồng tổng thể xuống còn đúng **0.35**.

#### Lý do thực nghiệm chọn hàm này:
Bằng cách loại bỏ các đặc trưng trống trong lịch sử khỏi mẫu số của hàm tính trọng số (ví dụ: bỏ qua trọng số của trace nếu sự cố lịch sử không có trace signature), sự cố `E03` đã khớp thành công với `INC-2025-08-02` với độ tương đồng lên tới **0.809** (thay vì bị kéo tụt xuống **0.35**).

---

### 2. Việc bỏ phiếu trọng số kết quả (outcome-weighted voting) thay đổi thứ hạng ứng viên như thế nào so với việc chỉ xếp hạng theo độ tương đồng thuần túy?

Bỏ phiếu trọng số kết quả giúp ngăn chặn hệ thống đề xuất các hành động từng thất bại trong lịch sử đối với các sự cố tương tự.

#### Minh họa cụ thể qua sự cố E03:
Trong `E03`, hai sự cố lịch sử gần nhất có điểm tương đồng là:
1. `INC-2025-08-02` (memory_leak, kết quả: `success`, độ tương đồng = 0.809) $\rightarrow$ bỏ phiếu $+0.809$ cho hành động `rollback_service`.
2. `INC-2025-11-08` (pool exhaustion, kết quả: `success`, độ tương đồng = 0.474) $\rightarrow$ bỏ phiếu $+0.474$ cho `rollback_service` và `increase_pool_size`.

Nếu có một sự cố lịch sử tương tự nhưng hành động khắc phục bị thất bại (`outcome == "failed"`), trọng số bầu chọn của hành động đó sẽ bị trừ đi (nhân với hệ số `-1.0`).
Ngoài ra, xác suất thành công ($P_{success}$) của từng hành động được tính tỷ lệ dựa trên điểm bầu chọn của nó so với hành động có điểm cao nhất. 
Vì `increase_pool_size` chỉ nhận được phiếu bầu từ hàng xóm yếu hơn (`INC-2025-11-08`), điểm bầu chọn của nó chỉ đạt `0.474` so với `2.092` của `rollback_service`. Điều này kéo giảm $P_{success}$ của nó xuống còn **0.18**, dẫn đến điểm EV bị âm nặng và giúp `rollback_service` giành chiến thắng.

---

### 3. Giải thích chi tiết tính toán EV cho một sự cố thử nghiệm

Xem xét sự cố **E03** (Memory Leak trên dịch vụ `esb`):

#### Danh sách ứng viên và điểm bầu chọn (Consensus Score):
- `rollback_service:esb`: Điểm = `2.092` (Điểm tối đa - Max Score)
- `increase_pool_size:esb`: Điểm = `0.474`
- `page_oncall`: Điểm = `0.0` (Phương án dự phòng)

#### Tính toán giá trị kỳ vọng (Expected Value - EV):
- **`rollback_service:esb`**:
  - $P_{success} = 0.809 \times \frac{2.092}{2.092} = 0.81$
  - Hình phạt (Penalty): $\text{cost\_min} + 2 \cdot \text{downtime\_min} + 5 \cdot \text{blast\_radius} = 10 + 2\cdot 2 + 5\cdot 1 = 19$
  - $EV = 0.81 \cdot (100 - 19) + 0.19 \cdot (-150 - 19) = 33.25$
- **`increase_pool_size:esb`**:
  - $P_{success} = 0.809 \times \frac{0.474}{2.092} = 0.18$
  - Hình phạt (Penalty): $1 + 2\cdot 0 + 5\cdot 1 = 6$
  - $EV = 0.18 \cdot (100 - 6) + 0.82 \cdot (-150 - 6) = -110.17$
- **`page_oncall`**:
  - $P_{success} = 0.99$ (Kỹ sư được gọi sẽ giải quyết được sự cố)
  - Hình phạt (Penalty): $0 + 2\cdot 0 + 5\cdot 0 + 70.0 \text{ (hình phạt chi phí ảo)} = 70.0$
  - $EV = 0.99 \cdot (100 - 70.0) + 0.01 \cdot (-150 - 70.0) = 27.5$

#### Kết quả chọn hành động:
Hành động `rollback_service` trên dịch vụ `esb` chiến thắng vì có điểm EV cao nhất (**33.25** so với **27.5** của `page_oncall`, chênh lệch **5.75** điểm).

---

### 4. Khi nào động cơ quyết định leo thang (page_oncall) thay vì tự động xử lý?

Động cơ quyết định leo thang (gọi kỹ sư on-call) trong hai trường hợp chính sau:

1. **Phát hiện lỗi mới (OOD Detection - Độ tương đồng tối đa < 0.35)**:
   - `E02` (TLS cert hết hạn, độ tương đồng cao nhất = 0.309) — (yêu cầu thao tác chứng chỉ thủ công).
   - `E04` (Lỗi DNS NXDOMAIN, độ tương đồng cao nhất = 0.208).
   - `E05` (Tranh chấp khóa lock contention, độ tương đồng cao nhất = 0.293).
   - `E08` (Lan truyền lỗi đồ thị topology, độ tương đồng cao nhất = 0.306).
2. **Giá trị kỳ vọng (EV) của tất cả hành động tự động bị âm**:
   - `E06` (Xung đột logs/traces) — Điểm EV của `rollback_service` bị kéo xuống còn `-45.75` do độ tin cậy thấp, nhường chiến thắng cho `page_oncall` ($EV = 27.5$).
   - `E07` (Nghẽn API Kubernetes).


---

### 5. Dạng sự cố nào dễ làm lỗi động cơ nhất?

#### Dạng sự cố:
**Sự cố đa lỗi đồng thời (Multi-fault cascading incidents)** xảy ra khi hai nguyên nhân lỗi không liên quan xuất hiện cùng một lúc (ví dụ: vừa bị memory leak trên `notification-svc` vừa bị slow query trên cơ sở dữ liệu `catalog-db`).

#### Lý do gây lỗi:
Hệ thống giả định mỗi sự cố chỉ có một dịch vụ bị lỗi chính (bằng cách tìm kiếm nút lá lỗi sâu nhất thông qua duyệt topology). Trong tình huống đa lỗi, thuật toán sẽ chỉ chọn một trong hai dịch vụ và bỏ qua dịch vụ còn lại, dẫn đến việc rollback hoặc restart thiếu sót, không giải quyết triệt để sự cố.

#### Đề xuất cải tiến:
Xây dựng một bộ phân tách sự cố thành các đồ thị con độc lập dựa trên luồng traces và logs lỗi, sau đó thực hiện các phép tính EV và đưa ra quyết định riêng biệt cho từng đồ thị con lỗi đó. Cải tiến này chưa được triển khai do giới hạn thời gian của dự án và thực tế là tất cả 8 incident trong bài thi đều chỉ có một nguyên nhân lỗi chính duy nhất.

---

### 6. Giới hạn về Chữ ký Log dựa trên Substring Matching cứng (Rule-based Substring Log Parsing)

#### Dạng sự cố:
**Sự cố phát sinh log định dạng mới** hoặc **Sự cố trên các dịch vụ mới cập nhật** trong hệ thống sản xuất mở rộng (Open-World).

#### Lý do gây lỗi:
Hàm `map_log_message_to_signature` trong [features.py](file:///d:/Xbrain/lab-w2-evidence-driven-remediation-20260611/data-pack/features.py) sử dụng các câu điều kiện `if "..." in msg_lower` cứng. Khi có dịch vụ mới triển khai hoặc phiên bản phần mềm mới thay đổi định dạng log (ví dụ: thay đổi chữ hoa/thường, thêm bớt từ khóa thông báo lỗi), cơ chế so khớp cứng này sẽ trả về `None`. Live log bị bỏ sót sẽ làm giảm điểm tương đồng Jaccard một cách nhân tạo, kích hoạt OOD sai (false positive OOD) và tự động leo thang lên `page_oncall` một cách không cần thiết.

#### Thuật toán thay thế cụ thể (Drain3 / Dynamic Log Parser):
Nếu triển khai cải tiến này, thuật toán xử lý log sẽ thay đổi hoàn toàn như sau:
1. **Huấn luyện Offline (Offline Template Extraction)**:
   * Cho thuật toán **Drain3** duyệt qua toàn bộ logs thô trong tập lịch sử để tự động gom cụm và sinh ra cây phân tích (Parse Tree), trích xuất các log template động (ví dụ: `OutOfMemoryError: <*>` thay thế cho các biến số cụ thể).
   * Mỗi template được gán một mã định danh duy nhất (`template_id`).
2. **Khớp Log trực tuyến (Online Log Parsing)**:
   * Khi có live incident, logs thô sẽ đi qua bộ phân tích Drain3 trực tuyến. Drain3 sẽ duyệt dọc Parse Tree để khớp dòng log thô vào `template_id` có cấu trúc tương thích gần nhất dựa trên số lượng token tĩnh.
3. **So sánh tương đồng Jaccard trên IDs**:
   * Phép so sánh tương đồng logs giữa live incident và historical incident sẽ được chuyển từ đối sánh chuỗi thô sang tính chỉ số Jaccard trực tiếp trên tập hợp các `template_id`.
4. **Cơ chế Fallback cho log lạ (Novel Log Fallback)**:
   * Nếu dòng log thô sinh ra một `template_id` mới hoàn toàn chưa từng xuất hiện trong Parse Tree, hệ thống vẫn ghi nhận `template_id` này như một đặc trưng mới (thay vì trả về `None`). Điểm số Jaccard lúc này sẽ phản ánh chính xác sự xuất hiện của các log lạ này để làm tăng trọng số OOD một cách khách quan.