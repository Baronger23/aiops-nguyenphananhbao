# AI Engine Spec - FinOps Watch (Task Force 2)

<!-- Doc owner: Nhóm AI
     Status: Final (W11 T6 Pack #1)
     Word count: ~3800 từ
     Reference: TCB DAB Framework - AI Model Governance + AI Security (adapted for capstone) -->

## 1. Model architecture

Chúng tôi lựa chọn mô hình **Hybrid (Kết hợp giữa Thống kê Toán học và Mô hình Ngôn ngữ Lớn - LLM)** để tối ưu hóa chi phí vận hành, đảm bảo độ trễ thấp và độ giải trình cao.

-   **Pattern chọn**: **Statistical Filter (Log Transform + Holt-Winters) + NetworkX Graph Correlation + Single-shot LLM (Structured JSON Output)**.
    *   **Giai đoạn 1 (Lọc sơ cấp)**: Chuỗi dữ liệu chi phí thô có độ lệch lớn (Skewed Data) được biến đổi toán học bằng **Log Transform** trước khi đưa vào thuật toán thống kê Holt-Winters.
    *   **Giai đoạn 2 (Phân tích đồ thị RCA)**: Nếu Holt-Winters phát hiện bất thường chi phí, hệ thống tự động chạy **NetworkX Topology Graph** để kết nối chi phí với CloudWatch utilization (CPU/RAM) và tìm kiếm vết trong log CloudTrail (qua bộ tách log Drain3).
        *   Nếu CPU utilization tăng cao tương ứng -> Phân loại là **Business Growth** -> Kết quả là `ALERT_ONLY` hoặc `anomaly: false` (không gọi LLM).
        *   Nếu CPU idle -> Phân loại là **Culprit** (Thủ phạm gây lãng phí) -> Gọi LLM phân tích nguyên nhân gốc rễ.
    *   **Giai đoạn 3 (Giải trình LLM)**: Claude 3.5 Haiku được gọi bằng cơ chế Async để đọc dữ liệu và sinh JSON chứa giải trình bằng ngôn ngữ tài chính.
-   **Lý do lựa chọn**:
    *   *Tiết kiệm chi phí*: Giảm tới 95% số lượng token gọi LLM do loại bỏ được cả Business Growth và các ngày bình thường.
    *   *Độ trễ thấp*: FastAPI Async đảm bảo không nghẽn luồng xử lý đồng thời cho 12 squads.

---

## 2. Model selection

Chúng tôi lựa chọn sử dụng mô hình **Anthropic Claude 3.5 Haiku** được cung cấp dưới dạng Serverless API trên nền tảng AWS Bedrock.

| Field | Value |
|---|---|
| **Provider** | AWS Bedrock (Managed Service) |
| **Model ID** | `anthropic.claude-3-5-haiku-20241022-v1:0` |
| **Region** | Biến môi trường động `${AWS_REGION}` |
| **Context window** | 200,000 tokens |
| **Cost/1k input tokens** | $0.0008 |
| **Cost/1k output tokens**| $0.0040 |
| **Estimated per-call cost**| ~$0.00096 |

---

## 3. Multi-tenant routing

Hệ thống được thiết kế để phục vụ multi-tenant (12 squad kỹ sư độc lập) với sự phân tách tuyệt đối:

-   **Tenant identification**: AI Engine trích xuất `tenant_id` từ Request Header `X-Tenant-Id` của API Gateway.
-   **Context isolation**: Việc xử lý prompt được cô lập hoàn toàn trên RAM theo từng request. Hệ thống không lưu trữ trạng thái phiên (session state) hoặc lịch sử trò chuyện (chat history) giữa các request khác nhau của cùng một tenant hoặc khác tenant để loại bỏ rủi ro rò rỉ chéo.
-   **State & Audit storage**: Lưu nhật ký kiểm toán vào DynamoDB với Khóa phân vùng (Partition Key) là `tenant_id` và Khóa sắp xếp (Sort Key) là `audit_id`. Phân quyền IAM Policy trên bảng DynamoDB được thắt chặt bằng cấu hình `LeadingKeys` để mỗi tenant chỉ được đọc log của chính mình.

---

## 4. Prompt engineering / RAG strategy

### 4.1 System prompt

Mô hình Claude được chỉ thị đóng vai trò là một chuyên gia FinOps cao cấp phục vụ CFO. Các tham số về ngưỡng thời gian không hoạt động (idle hours thresholds) sẽ được truyền động vào prompt dựa trên cấu hình riêng biệt của từng Tenant để chấm điểm độ tin cậy (configurable confidence system), loại bỏ các con số fix cứng. Dưới đây là nội dung mẫu prompt:

```
Role: Bạn là Chuyên gia FinOps cao cấp được CFO ủy quyền để kiểm soát chi phí AWS Organizations.
Nhiệm vụ: Phân tích dữ liệu chi phí bất thường được gửi lên, giải trình nguyên nhân gốc rễ và đề xuất hành động ngăn chặn (containment).

Quy tắc bắt buộc về ngôn ngữ giải trình (reasoning):
- Tuyệt đối KHÔNG sử dụng các từ ngữ kỹ thuật/thuật toán (như "variance", "z-score", "Isolation Forest", "phương sai", "độ lệch chuẩn", "ngưỡng 3-sigma", "Holt-Winters", "Log Transform", "networkx", "Drain3"). CFO không hiểu các từ này.
- Bắt buộc phải giải trình bằng ngôn ngữ tài chính và số liệu kinh tế thực tế. Cụ thể bao gồm:
  + Dịch vụ nào đang gây ra chi phí tăng (ví dụ: EC2, SageMaker, RDS...).
  + Tỉ lệ tăng hoặc số tiền cụ thể bị lãng phí (ví dụ: "tăng 2.3 lần", "tiêu tốn $400/ngày").
  + Lý do phát sinh dưới góc nhìn tài nguyên và nhật ký log (ví dụ: "máy chạy không tải liên tục trong 18 ngày", "phát hiện API CreateTrainingJob khởi tạo cluster nhưng không có lệnh Stop/Delete tương ứng trong 18 ngày").
  + Ước tính số tiền lãng phí tích lũy nếu không xử lý.

Đề xuất hành động (suggested_action) dựa trên môi trường (environment):
- Môi trường "prod": Chỉ được chọn "TAG_FOR_REVIEW" hoặc "ALERT_ONLY". Tuyệt đối không bao giờ được hạ quota hay tắt máy ảo.
- Môi trường "dev" hoặc "sandbox": Có thể chọn "QUOTA_CAP" hoặc "SCHEDULE_SHUTDOWN" nếu chi phí lãng phí lớn (> $100/ngày).

Quy tắc chấm điểm độ tin cậy (confidence) của hành động:
Hãy tính điểm tin cậy toán học theo trọng số thực tế sau và gán vào trường "confidence" (sử dụng các ngưỡng cấu hình động được truyền vào):
- Thiếu thẻ tag quan trọng (Owner/Project) = 0.3 điểm.
- Thời gian tài nguyên không hoạt động (idle):
  + idle_hours_continuous >= {idle_threshold_high} giờ = 0.5 điểm.
  + idle_hours_continuous >= {idle_threshold_normal} giờ = 0.3 điểm.
  + idle_hours_continuous < {idle_threshold_normal} giờ = 0.1 điểm.
- Log phát hiện Drain3 cluster (Create nhưng không Delete/Stop) = 0.2 điểm.
- Điểm confidence = min(1.0, tổng các điểm trên). Nếu có lý do bất thường khác mà không có dữ liệu idle, tự thiết lập confidence dựa trên mức độ bất thường chi phí của CUR.

Đầu ra bắt buộc phải tuân thủ định dạng JSON khớp với JSON Schema sau:
{
  "anomaly": true,
  "severity": <float 0.0-1.0>,
  "suggested_action": "TAG_FOR_REVIEW" | "QUOTA_CAP" | "SCHEDULE_SHUTDOWN" | "ALERT_ONLY" | "INVESTIGATE",
  "reasoning": "<chuỗi giải trình tối đa 300 ký tự tiếng Việt>",
  "confidence": <float 0.0-1.0>,
  "details": {
    "daily_waste_usd": <float>,
    "runaway_days": <int>,
    "affected_resource": "<resource_id>",
    "ratio_increase": <float>
  }
}
```

### 4.2 User prompt template

```
Dữ liệu bất thường phát hiện:
- Tenant ID: {tenant_id}
- Tên dịch vụ: {service}
- Tài nguyên ảnh hưởng: {resource_id}
- Môi trường: {environment}
- Squad sở hữu: {squad_owner}
- Chi phí ngày hôm nay: ${actual_cost}
- Chi phí trung bình baseline: ${baseline_cost}
- Tín hiệu bổ sung:
  + Số giờ không tải liên tục (idle_hours_continuous): {idle_hours}
  + Các tag bị thiếu (missing_tags): {missing_tags}
  + Kết quả Log Mining (Drain3): {drain3_log_summary}

Hãy thực hiện phân tích và xuất dữ liệu JSON theo đúng yêu cầu hệ thống.
```

---

## 5. Phân tích nền tảng & Quản trị AI (W1 - W3)

### 5.1 Xử lý dữ liệu toán học (Log Transform & Holt-Winters)
Dữ liệu chi phí CUR thường có độ lệch (skewness) rất cao do các spike đột biến. Để tránh làm méo mó các khoảng tin cậy của mô hình Holt-Winters, chúng tôi áp dụng phép biến đổi Log Transform:
\[y_t = \ln(x_t + 1)\]
Trong đó \(x_t\) là chi phí thô của ngày \(t\). Thuật toán Holt-Winters (Triple Exponential Smoothing) sẽ dự báo trên chuỗi biến đổi \(y_t\) này. Khoảng tin cậy sau đó được giải biến đổi (Inverse Log Transform) để xác định ngưỡng phát hiện bất thường thực tế.
*   **Warm-up Window**: Yêu cầu tối thiểu 14 ngày dữ liệu chuỗi lịch sử để mô hình tự học tính chu kỳ tuần \(L = 7\) ngày.

### 5.2 Log Mining phân tích hoạt động API (Drain3 Log Parsing)
Nhóm CDO sẽ định kỳ đẩy log CloudTrail thô của tài nguyên vào hệ thống. AI Engine nhúng bộ phân tích **Drain3** để gom cụm các sự kiện API:
*   Drain3 phân tích log thành các mẫu template (ví dụ: `User: <user> called CreateTrainingJob for resource: <resource>`).
*   Nếu phát hiện sự kiện tạo (`CreateTrainingJob`, `RunInstances`) mà không xuất hiện sự kiện xóa/dừng tương ứng (`DeleteTrainingJob`, `TerminateInstances`) của cùng một tài nguyên trong cửa sổ 14 ngày, AI Engine sẽ xác định đây là bằng chứng thép của sự lãng phí ("runaway cluster") và đẩy trực tiếp bằng chứng này vào prompt của LLM.

### 5.3 Topology-aware Graph RCA & Dynamic Node Spawning (networkx)
Để liên kết (correlate) các alert và phân loại nguyên nhân, AI Engine xây dựng một đồ thị quan hệ tài nguyên bằng thư viện `networkx`:
*   **Các nút (Nodes)**: Tài nguyên (resource_id), Squad sở hữu, Môi trường, và chỉ số tải (CPU/RAM).
*   **Các cạnh (Edges)**: Mối quan hệ phụ thuộc hoặc liên kết phân bổ.
*   **Quy tắc phân tách nút động (Dynamic Node Spawning)**:
    *   Khi resource_id rơi vào nhãn Fallback (`service-level-aggregate` hoặc `unallocated-unmapped`), để tránh biến NetworkX Graph thành một nút độc lập dùng chung (gây mù quáng mô hình/mất ngữ cảnh liên kết), code AI Engine tự động phân tách thành các nút con cụ thể như `service-level-aggregate:vpc-0abcdef` hoặc `service-level-aggregate:account-1234` dựa trên thông tin định vị không gian trong `fallback_context`.
*   **Quy tắc ra quyết định**:
    *   *Nhánh Business Growth*: Nếu chi phí tăng vọt đồng thời CPU nút tài nguyên đạt 95% liên tục -> Đồ thị xác định là biến động kinh doanh hợp lệ -> Đè hành động về `ALERT_ONLY` / `anomaly: false`.
    *   *Nhánh Culprit*: Chi phí tăng vọt nhưng CPU nút tài nguyên < 5% (idle) -> Đồ thị xác định tài nguyên này là Culprit gây lãng phí -> Đề xuất auto-containment (`SCHEDULE_SHUTDOWN`).

### 5.4 Quản trị bằng Error Budget Gate cô lập (Isolated Per-Tenant Error Budget)
Hệ thống thiết lập cơ chế khóa cứng an toàn dựa trên ngân sách lỗi:
*   **SLI (Chỉ số đo lường)**: Tỉ lệ rollback/verify fail của các hành động tự động ngăn chặn trên sandbox/dev trong 24 giờ.
*   **SLO (Mục tiêu chất lượng)**: Tỉ lệ can thiệp lỗi < 1% (Error Budget cho phép là 1%).
*   **Enforcement (Gating cô lập)**:
    *   Trạng thái Error Budget được lưu và đếm trong DynamoDB dựa trên Partition Key là `tenant_id` (hoặc `squad_id`).
    *   Nếu Squad-12 liên tục chạy can thiệp sai và đốt hết ngân sách lỗi của riêng họ (> 1%), AI Engine sẽ lập tức **Khóa cứng (Hard Lock)** tính năng tự động can thiệp của duy nhất Squad-12 và hạ toàn bộ các hành động của squad này về `ALERT_ONLY`.
    *   11 Squads còn lại vẫn hoạt động hoàn toàn bình thường, bảo vệ tính cô lập và toàn vẹn của kiến trúc Multi-tenant cấp Enterprise.

### 5.5 Kiểm thử tiêm dữ liệu giả lập ở tầng kho (Staging Data Layer Injection Chaos Test)
Để kiểm định khả năng phục hồi khép kín (closed-loop) một cách thực tế và vượt qua hạn chế độ trễ tự nhiên của AWS CUR (8-24 tiếng):
*   Script test chaos (`chaos_runner.py`) sẽ bỏ qua việc can thiệp vào AWS Account thật.
*   Thay vào đó, nó can thiệp trực tiếp vào bảng Staging Data Warehouse của CDO hoặc giả lập emit một payload JSON chứa chuỗi chi phí tăng vọt $1000/h đè thẳng vào API `/v1/detect` của AI Engine.
*   *Mục tiêu nghiệm thu*: Đo lường xem từ thời điểm dữ liệu lỗi xuất hiện tại cửa ngõ tiếp nhận, hệ thống mất bao nhiêu giây để hoàn thành toàn bộ chuỗi logic rẽ nhánh, gọi LLM, ghi sổ Audit Store và kích hoạt lệnh can thiệp. Mục tiêu hoàn toàn thực tế là chu kỳ khép kín diễn ra dưới **10 giây**.

---

## Related documents

*   [`02_solution_design.md`](02_solution_design.md) - Thiết kế luồng dữ liệu tổng quan
*   [`../contracts/ai-api-contract.md`](../contracts/ai-api-contract.md) - Thỏa thuận API với CDO
*   [`05_adrs.md`](05_adrs.md) - Ghi nhận các quyết định kiến trúc cụ thể
