# Architecture Decision Records - FinOps Watch (Task Force 2)

<!-- Doc owner: Nhóm AI
     Status: Ongoing log W11-W12
     Format: 1 ADR per major decision. Append-only - không xóa ADR cũ. -->

Tài liệu này ghi lại các quyết định thiết kế kiến trúc quan trọng cho AI Engine thuộc dự án FinOps Watch, bao gồm bối cảnh, quyết định, hệ quả và các phương án thay thế được cân nhắc.

---

## ADR-001 - Lựa chọn thuật toán Holt-Winters (Triple Exponential Smoothing) để lọc bất thường có chu kỳ tuần

-   **Status**: Accepted
-   **Date**: 2026-06-22
-   **Context**: 
    Chi phí dịch vụ AWS (CUR) của công ty phân phối không đều và chịu ảnh hưởng mạnh bởi tính chu kỳ tuần (Thứ 7 - CN tắt máy/giảm tải, Thứ 2 bật lại gây vọt chi phí). Hệ thống cần một bộ lọc sơ cấp có khả năng tự thích ứng với tính chu kỳ này để tránh báo động giả vào ngày đầu tuần mà không tốn chi phí gọi LLM liên tục.
-   **Decision**: 
    Lựa chọn thuật toán **Holt-Winters (Triple Exponential Smoothing)** với chu kỳ $L = 7$ ngày làm bộ lọc bất thường sơ cấp (First-stage Filter) chạy trực tiếp trên RAM của AI Engine.
-   **Consequence**:
    -   ✅ **Thích ứng chu kỳ tự động**: Tự động học xu hướng tăng giảm theo ngày trong tuần, giảm thiểu False Positive ngày Thứ 2 xuống dưới 10%.
    -   ✅ **Hiệu năng cực nhanh**: Chạy trên RAM với độ phức tạp toán học $O(N)$, tốn chưa đầy 10ms xử lý dữ liệu baseline.
    -   ⚠️ **Yêu cầu dữ liệu khởi động**: Cần tối thiểu 14 ngày dữ liệu chuỗi lịch sử (Warm-up Window) để tự động tính toán các hệ số chu kỳ trước khi đưa ra dự báo ngày mới.
-   **Alternatives considered**:
    -   *Isolation Forest*: Thích hợp cho outlier đa chiều nhưng không tự thích ứng tốt với tính chu kỳ tuần của chuỗi thời gian 1 chiều nếu không bổ sung kỹ thuật trích xuất đặc trưng (feature engineering) phức tạp.
    -   *Ngưỡng tĩnh Z-Score (3-Sigma)*: Quá đơn giản, không học được tính chu kỳ tuần dẫn đến báo động giả hàng loạt vào ngày Thứ 2.

---

## ADR-002 - Thiết lập chu kỳ phân tích (Cadence) 24 giờ trên dữ liệu ngày hôm trước (T-1)

-   **Status**: Accepted
-   **Date**: 2026-06-22
-   **Context**: 
    CFO yêu cầu phát hiện bất thường nhanh chóng. Tuy nhiên, file hóa đơn thô AWS CUR trong S3 có độ trễ tự nhiên (lag) từ 8 đến 24 tiếng để AWS tổng hợp dữ liệu hóa đơn. Việc gọi API phân tích theo thời gian thực (real-time sub-second) là bất khả thi về mặt vật lý và gây tốn kém chi phí gọi API.
-   **Decision**: 
    Thiết lập chu kỳ quét phân tích (Cadence) định kỳ mỗi **24 giờ**, sử dụng dữ liệu chi phí đã hoàn tất tổng hợp của ngày hôm trước ($T-1$).
-   **Consequence**:
    -   ✅ **Dữ liệu tin cậy**: Giảm thiểu False Positive do dữ liệu CUR bị thiếu hoặc chưa kịp cập nhật đầy đủ từ AWS.
    -   ✅ **Tối ưu chi phí**: Hệ thống chỉ chạy phân tích 1 lần/ngày đối với mỗi tenant, hạn chế tối đa chi phí vận hành và token Bedrock.
    -   ⚠️ **Độ trễ phát hiện**: Sự cố tăng vọt chi phí sẽ được phát hiện chậm hơn 8-24 tiếng so với thời điểm phát sinh thực tế.
-   **Alternatives considered**:
    -   *Cadence Real-time / Sub-hour*: Bị loại bỏ vì AWS Cost Explorer API bị giới hạn tần suất gọi (rate-limited) và chi phí rất cao, trong khi CUR không hỗ trợ streaming thời gian thực.
    -   *Cadence 48 giờ*: Trễ quá lâu, khiến doanh nghiệp mất thêm nhiều tiền lãng phí trước khi hệ thống phát hiện. 24 giờ là điểm cân bằng tối ưu.

---

## ADR-003 - Triển khai cơ chế Idempotency dựa trên DynamoDB Audit Store với Khóa Composite & 24h TTL

-   **Status**: Accepted (Updated)
-   **Date**: 2026-06-22
-   **Context**: 
    Để tránh việc gọi trùng lặp (double-run) gây tốn kém token LLM Bedrock và ghi đè audit logs, hệ thống cần cơ chế kiểm tra idempotency. Tuy nhiên, nếu CDO sử dụng khóa tĩnh (static key) hoặc lặp lại code cũ từ ngày hôm trước, hệ thống có thể trả về cache lỗi thời và bỏ sót bất thường mới.
-   **Decision**: 
    - Bắt buộc CDO gửi `X-Idempotency-Key` dưới dạng khóa composite ràng buộc thời gian: `[tenant_id]_[billing_period_YYYYMMDD]_[batch_sequence_id]`.
    - AI Engine sẽ validate định dạng key bằng regex, từ chối các key sai định dạng (trả về 400 Bad Request).
    - Thiết lập thuộc tính TTL (Time-To-Live) cho các bản ghi Idempotency trong DynamoDB là 24 giờ.
-   **Consequence**:
    -   ✅ **Triệt tiêu đè dữ liệu**: Ép CDO phải thay đổi khóa sang ngày mới nếu sang chu kỳ mới, tránh cache đè lịch sử.
    -   ✅ **Giải phóng dung lượng**: Khóa tự động xóa sau 24h giúp tối ưu chi phí lưu trữ DynamoDB.
    -   ⚠️ **Độ chặt chẽ của Client**: CDO phải tuân thủ nghiêm ngặt thuật toán sinh key để không bị lỗi 400.

---

## ADR-004 - Áp dụng Log Transform tiền xử lý dữ liệu chi phí bị lệch (Skewed Cost Data) trước khi chạy Holt-Winters

-   **Status**: Accepted
-   **Date**: 2026-06-22
-   **Context**: 
    Hóa đơn chi phí AWS (CUR) phân phối rất lệch (heavy-tailed / skewed distribution) do các spike đột biến. Holt-Winters dựa trên giả định phân phối chuẩn của sai số, khi chạy trên dữ liệu gốc sẽ làm méo mó các khoảng tin cậy (Confidence Bands), dẫn đến báo động sai (False Positives) liên tục hoặc bỏ sót bất thường nhỏ.
-   **Decision**: 
    Áp dụng công thức Log Transform \(y_t = \ln(x_t + 1)\) trước khi nạp chuỗi chi phí vào bộ lọc Holt-Winters. Toàn bộ khoảng dự báo được tính toán trên không gian log, sau đó giải biến đổi (exponential) về giá trị gốc để đưa ra ngưỡng cảnh báo chi phí thực tế.
-   **Consequence**:
    -   ✅ **Ổn định hóa biến động**: Normalize phân phối dữ liệu chi phí lệch, nén biên độ của các spike lớn.
    -   ✅ **Hạn chế báo giả**: Giảm thiểu tối đa False Positive ngày Thứ 2 đầu tuần khi chi phí bật trở lại.
    -   ⚠️ **Mất mát số học nhỏ**: Việc log transform có thể làm giảm độ nhạy đối với các spike cực nhỏ nếu không cấu hình ngưỡng tin cậy chặt chẽ.
-   **Alternatives considered**:
    -   *Chạy Holt-Winters trực tiếp trên chi phí gốc*: Bị loại bỏ vì tỷ lệ báo giả vượt quá 15% do dữ liệu thô lệch quá lớn.

---

## ADR-005 - Sử dụng Đồ thị Topology NetworkX để liên kết (Correlate) cảnh báo và phân loại nguyên nhân

-   **Status**: Accepted
-   **Date**: 2026-06-22
-   **Context**: 
    Việc chỉ dựa vào hóa đơn tăng vọt để cảnh báo sẽ gây phiền hà cho kỹ sư nếu đó là tăng tải hợp lệ do tăng trưởng kinh doanh (Business Growth). AI Engine cần phân biệt được lãng phí thực sự (Culprit) và hoạt động kinh doanh hợp lệ mà không cần gọi LLM liên tục.
-   **Decision**: 
    Xây dựng một Topology Graph thu nhỏ trong bộ nhớ bằng thư viện **NetworkX** để map quan hệ tài nguyên, squad sở hữu, môi trường và chỉ số tải (CPU/RAM).
    - Nếu chi phí tăng vọt đồng thời CPU nút tài nguyên đạt 95% liên tục -> Đồ thị tự động gom cụm phân loại là **Business Growth** -> Chỉ gửi cảnh báo thường (`ALERT_ONLY`).
    - Nếu chi phí tăng vọt nhưng CPU idle (< 5%) -> Phân loại là **Culprit** -> Đề xuất auto-containment (`SCHEDULE_SHUTDOWN`).
-   **Consequence**:
    -   ✅ **Lọc cảnh báo rác**: Phân biệt chính xác nguyên nhân kỹ thuật mà không cần con người can thiệp.
    -   ✅ **Tiết kiệm chi phí**: Giảm 50% số lần gọi Bedrock vì các biến động Business Growth hợp lệ được xử lý thẳng ở tầng đồ thị.
    -   ⚠️ **Độ phức tạp**: Phải cập nhật đồ thị NetworkX liên tục dựa trên thông tin hạ tầng CDO cung cấp qua request.
-   **Alternatives considered**:
    -   *Gửi toàn bộ metrics thô cho Claude tự suy luận*: Bị loại bỏ vì làm tăng kích thước prompt (tốn tiền) và Claude khó tính toán chính xác mức độ tương quan tải.

---

## ADR-006 - Thiết lập Error Budget Gate cô lập theo từng Tenant (Isolated Per-Tenant Error Budget)

-   **Status**: Accepted (Updated)
-   **Date**: 2026-06-22
-   **Context**: 
    Cơ chế khóa cứng toàn hệ thống (Global Hard Lock) khi cạn kiệt Error Budget có điểm yếu nghiêm trọng: nếu một squad duy nhất chạy can thiệp sai liên tục và làm cháy hết ngân sách lỗi chung, toàn bộ 11 squad còn lại cũng bị khóa cứng tính năng auto-containment một cách vô lý (lỗi cô lập tenant).
-   **Decision**: 
    Phân rã theo dõi và đếm Error Budget theo từng `tenant_id` độc lập trong DynamoDB. 
    Khi một tenant bị vượt quá 1% lỗi, AI Engine chỉ khóa cứng (Hard Lock) hành động tự động ngăn chặn của tenant đó về `ALERT_ONLY`. Các tenant khác không bị ảnh hưởng.
-   **Consequence**:
    -   ✅ **Tính cô lập cao**: Đạt tiêu chuẩn Multi-tenant của kiến trúc Enterprise.
    -   ✅ **Vận hành liên tục**: Hạn chế ảnh hưởng chéo (blast radius) giữa các đội phát triển.
    -   ⚠️ **Quản trị phức tạp**: Phải theo dõi và reset ngân sách lỗi theo từng tenant ID cụ thể.

---

## ADR-007 - Áp dụng Async Polling Pattern cho Endpoint `/v1/detect` để loại bỏ nguy cơ sập kết nối

-   **Status**: Accepted
-   **Date**: 2026-06-22
-   **Context**: 
    Cam kết API Latency là <500ms, nhưng nhánh Bedrock phân tích và sinh giải trình RCA tốn tới 10 giây. Mô hình Request-Response đồng bộ sẽ gây nghẽn kết nối (Connection Pool Exhaustion) tại API Gateway hoặc client timeout khi có nhiều request đồng thời.
-   **Decision**: 
    Chuyển dịch endpoint `/v1/detect` hoàn toàn sang mô hình Bất đồng bộ thực sự (Async Polling Pattern):
    - `POST /v1/detect`: Nhận request, đẩy tác vụ vào hàng đợi xử lý ngầm (FastAPI BackgroundTasks), lập tức trả về `202 Accepted` kèm `audit_id` trong vòng <50ms.
    - `GET /v1/status/{audit_id}`: CDO Platform polling trạng thái sau mỗi 2-3 giây để lấy kết quả từ DynamoDB Audit Store.
-   **Consequence**:
    -   ✅ **Bảo vệ hệ thống**: Giải phóng kết nối ngay lập tức, không gây nghẽn Connection Pool hay timeout.
    -   ✅ **Đáp ứng SLA**: Giữ vững cam kết Latency <500ms cho bước tiếp nhận và <10ms cho bước polling status.
    -   ⚠️ **Tăng số lượng request**: CDO phải thực hiện thêm các cuộc gọi polling làm tăng lượng traffic vào API Gateway (nhưng tải truy vấn DB siêu nhẹ <10ms).

---

## ADR-008 - Dynamic Tenant Configuration and Asynchronous Human Feedback Loop

-   **Status**: Accepted
-   **Date**: 2026-06-22
-   **Context**: 
    Hệ thống phục vụ 12 squads đa dạng về mô hình tải (Batch vs Online). Ngưỡng giờ nhàn rỗi (`idle_threshold`) cố định không đáp ứng được đặc thù của từng squad, dẫn đến việc can thiệp sai (False Positives). Ngoài ra, khi xảy ra can thiệp sai, kỹ sư thực hiện rollback thủ công, cần có cơ chế ghi nhận feedback này theo thời gian thực (asynchronous) để tự động cập nhật Ngân sách lỗi SLO (Error Budget) và gắn nhãn False Positive cho mục đích hậu kiểm.
-   **Decision**: 
    - Thống nhất ủy thác toàn bộ cấu hình ngưỡng động (idle thresholds và confidence weights) cho DynamoDB.
    - Mở rộng các endpoint quản trị: `GET/PUT /v1/tenants/{tenant_id}/config` để cập nhật cấu hình động của từng tenant và `POST /v1/tenants/{tenant_id}/error-budget/reset` để reset ngân sách lỗi.
    - Cung cấp endpoint feedback: `POST /v1/audit/{audit_id}/rollback` để ghi nhận sự kiện hoàn tác can thiệp thủ công từ kỹ sư, tự động đánh dấu case phân tích tương ứng là False Positive và tính vào tỷ lệ cháy ngân sách lỗi SLO của Tenant.
-   **Consequence**:
    -   ✅ **Cấu hình linh hoạt**: Loại bỏ các con số fix cứng trong mã nguồn, cho phép điều chỉnh ngưỡng phù hợp với từng squad.
    -   ✅ **Thu thập Feedback tự động**: Ghi nhận chính xác phản hồi từ con người để tinh chỉnh mô hình và kiểm soát chặt blast radius qua Error Budget.
    -   ⚠️ **Độ phức tạp hạ tầng**: Tăng thêm các truy vấn vào DynamoDB để lấy cấu hình động tại mỗi lượt phân tích (nhưng đã được tối ưu hóa qua DynamoDB caching/primary key).

---

## ADR-009 - Bulk Historical Ingestion and Offline Evaluation Architecture

-   **Status**: Accepted
-   **Date**: 2026-06-23
-   **Context**: 
    Yêu cầu của CFO về việc chạy thử nghiệm đánh giá thuật toán (Backtesting) trên 3 tháng dữ liệu lịch sử và chứng minh độ chính xác (Precision >= 80%, Recall >= 70%) đòi hỏi hệ thống phải tiếp nhận khối lượng dữ liệu khổng lồ. Việc truyền hàng loạt dữ liệu này qua API phát hiện bất thường thời gian thực (`POST /v1/detect`) sẽ làm cạn kiệt Connection Pool và gây timeout. Đồng thời, CDO Dashboard cần cơ chế truy vấn lịch sử các vụ bất thường theo khoảng thời gian để hiển thị giao diện đồ họa.
-   **Decision**: 
    - Xây dựng Endpoint nạp dữ liệu lịch sử hàng loạt độc lập: `POST /v1/tenants/{tenant_id}/history` để import dữ liệu time-series phục vụ Warm-up Window hoặc đánh giá ngoại tuyến.
    - Xây dựng Endpoint kích hoạt đánh giá Backtest chuyên dụng: `POST /v1/admin/backtest`. Khi được gọi, AI Engine mô phỏng chạy thuật toán Holt-Winters + Graph RCA trên tập dữ liệu lịch sử đã nạp, đối chiếu với danh sách incident thực tế (`expected_anomalies`) để tính toán ma trận nhầm lẫn (Confusion Matrix) và trả về báo cáo chất lượng (Precision, Recall, F1-Score).
    - Xây dựng Endpoint truy vấn lịch sử bất thường: `GET /v1/tenants/{tenant_id}/anomalies` để CDO Dashboard truy vấn các điểm bất thường overlay theo thời gian.
-   **Consequence**:
    -   ✅ **Bao quát nghiệp vụ**: Đáp ứng 100% yêu cầu nghiệm thu báo cáo Backtest của CFO và cung cấp dữ liệu cho Dashboard.
    -   ✅ **Tách biệt hiệu năng**: Quá trình mô phỏng Backtesting nặng được chạy tách biệt (offline/on-demand), không ảnh hưởng đến luồng API vận hành trực tuyến hàng ngày.
    -   ⚠️ **Lưu trữ dữ liệu lịch sử**: Hệ thống cần duy trì lưu trữ tạm thời mảng dữ liệu lịch sử lớn trên bộ nhớ hoặc Database chuyên dụng trước khi kích hoạt Backtest.
