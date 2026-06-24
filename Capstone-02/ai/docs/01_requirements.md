# Requirements - FinOps Watch (Task Force 2)

<!-- Doc owner: Nhóm AI
     Status: Final (W11 T6 Pack #1)
     Word count: ~1500 từ
     BA methodology: dùng 5W2H làm khung khi interview Client T2 W11 -->

## 1. Khách hàng nói

> "Tháng trước AWS bill của chúng tôi đột ngột tăng 2.3 lần, từ mức bình thường khoảng $180k lên tới $420k. Đội Finance mất cả tuần mới tìm ra nguyên nhân: một lập trình viên quên tắt cluster training trên SageMaker, đốt mất $400/ngày suốt 18 ngày liên tiếp. Đến khi phát hiện thì công ty đã lãng phí hơn $7,000.
>
> Tôi là CFO, tôi không muốn những vụ việc đốt tiền lãng phí vô lý này xảy ra nữa. Tôi cần một hệ thống FinOps Watch chạy liên tục để giám sát chi phí AWS, tự động phát hiện chi tiêu bất thường nhanh chóng, gửi cảnh báo đúng người (Finance xem riêng, Kỹ sư xem riêng) và tự động thực hiện các biện pháp ngăn chặn an toàn (như áp quota cap hoặc tắt máy ảo trên môi trường dev/sandbox) trước khi hóa đơn vọt lên quá cao."

---

## 2. Outcomes mong muốn (restate own words)

Dựa trên yêu cầu của CFO, nhóm AI xác định các kết quả cần đạt được như sau:
*   **Outcome 1 - Giám sát chi phí liên tục (Continuous Monitoring)**: Tự động hóa việc thu thập và chuẩn hóa dữ liệu chi phí thông qua Trục xương sống dữ liệu (Data Pipeline). CDO sẽ định kỳ đổ dữ liệu thô vào S3 Staging -> Lambda ETL làm sạch, xử lý dữ liệu khuyết thiếu -> Nạp vào kho dữ liệu sẵn sàng cho AI Engine.
*   **Outcome 2 - Phát hiện bất thường chính xác (Precise Anomaly Detection)**: Nhận diện nhanh chóng các hành vi tiêu tốn chi phí bất thường (runaway training cluster, idle resource, thiếu thẻ tag phân bổ chi phí) với độ chính xác cao để lọc bớt cảnh báo rác.
*   **Outcome 3 - Định tuyến cảnh báo thông minh (Smart Alert Routing)**: Tách biệt kênh cảnh báo. Đội Finance nhận báo cáo tóm tắt tài chính bằng ngôn ngữ kinh doanh thân thiện; đội Engineering nhận cảnh báo kỹ thuật chi tiết kèm tài nguyên bị lỗi để xử lý nhanh.
*   **Outcome 4 - Ngăn chặn lãng phí tự động và an toàn (Safe Auto-containment)**: Khi phát hiện bất thường trên dev/sandbox, hệ thống tự động can thiệp (containment), đồng thời luôn ghi nhận audit log để có thể khôi phục (rollback) nhanh chóng.

---

## 3. Success criteria (measurable)

Hệ thống phải đạt được các chỉ số đo lường hiệu quả như sau:

| Metric | Target | How to measure |
|---|---|---|
| **Precision (Độ chính xác)** | ≥ 80% | Số vụ bất thường chi phí thực sự / Tổng số vụ hệ thống phát hiện trên tập backtest 3 tháng. |
| **False Positive (Tỉ lệ báo giả)** | ≤ 10% | Số vụ cảnh báo sai / Tổng số vụ bình thường trên tập dữ liệu backtest 3 tháng. |
| **Recall (Tỉ lệ phát hiện thực)** | ≥ 70% | Số vụ bất thường hệ thống bắt được / Tổng số vụ bất thường thực tế xảy ra trong lịch sử. |
| **Phát giải trình thân thiện (Finance-friendly Reasoning)** | 100% | Toàn bộ trường `reasoning` trả về phải dùng ngôn ngữ tài chính (số tiền lãng phí, tỉ lệ tăng) thay vì thuật toán (z-score, p-value). |
| **SLO về độ an toàn can thiệp (Containment Safety SLO)** | **≥ 99%** | Tỉ lệ các hành động tự động ngăn chặn (SCHEDULE_SHUTDOWN) không bị kỹ sư bấm nút **Rollback** hoặc hệ thống báo **Verify Fail** trong vòng 24 giờ kể từ khi thực thi. |
| **Audit Trail Retention** | ≥ 90 ngày | Thời gian lưu trữ log ghi nhận toàn bộ hành động ngăn chặn (containment action) trong DynamoDB/S3. |

---

## 4. Constraints & Governance (Error Budget)

*   **Ràng buộc Ngân sách lỗi cô lập theo từng Tenant (Isolated Per-Tenant Error Budget Gating)**:
    *   Hệ thống thiết lập hạn mức lỗi cho AI Engine là **1%** tổng số lần auto-containment của từng Tenant trong tháng (tương ứng SLO 99%).
    *   Trạng thái Error Budget được lưu trữ độc lập theo khóa `tenant_id` (hoặc `squad_id`) trong DynamoDB.
    *   Nếu một Squad cụ thể liên tục chạy can thiệp sai và đốt hết ngân sách lỗi của riêng họ (> 1%), hệ thống tự động **khóa cứng (Hard Lock)** tính năng Auto-containment của **duy nhất Squad đó**, ép các hành động của squad đó quay về chế độ an toàn `ALERT_ONLY`. Các Squad còn lại vẫn hoạt động hoàn toàn bình thường, bảo vệ tính cô lập và tính toàn vẹn của kiến trúc Multi-tenant cấp Enterprise.
*   **Ngân sách hoạt động (Cost Ceiling)**: Chi phí vận hành chính hệ thống FinOps Watch không được vượt quá 5% tổng lượng chi phí tối ưu hóa dự kiến (~$200/tháng cho môi trường thử nghiệm).
*   **Không động vào Production**: **Tuyệt đối KHÔNG** terminate tài nguyên trên môi trường prod, KHÔNG xóa dữ liệu, KHÔNG tự ý thay đổi quyền IAM (3 ranh giới cứng đã chốt).
*   **Môi trường áp dụng**: Các hành động ngăn chặn tự động chỉ được thực hiện trên môi trường **Dev và Sandbox**. Trên môi trường Prod, chỉ thực hiện gắn thẻ đánh dấu review (`Tag-for-Review`) hoặc cảnh báo (Dry-run mode).
*   **Phạm vi hạ tầng**: Chỉ áp dụng cho đám mây AWS (không làm multi-cloud).

---

## 5. Out of scope

Các công việc hệ thống sẽ **KHÔNG** thực hiện trong phạm vi dự án này:
*   ❌ Dự báo chi phí tương lai dài hạn (3 tháng trở lên) hoặc lập kế hoạch ngân sách (Budget Planning).
*   ❌ Công cụ đề xuất mua Reserved Instances (RI) hoặc Savings Plans (SP) tự động giao dịch.
*   ❌ Tích hợp với các bên thứ ba như CloudHealth, Apptio hoặc Vantage.
*   ❌ Tự động sửa đổi IAM policy hoặc thay đổi quyền truy cập bảo mật.
*   ❌ Tính năng đối soát chi phí (Showback/Chargeback billing) giữa các phòng ban.

---

## 6. Non-functional requirements

*   **Cadence phân tích (Time frame goal)**: Phân tích chi phí định kỳ mỗi **24 giờ**. Đây là điểm tối ưu cân bằng giữa độ trễ CUR của AWS (8-24 tiếng) và tốc độ ngăn chặn để giảm tối thiểu FP.
*   **Hiệu năng API & Quỹ thời gian trễ (Latency Budget)**:
    *   **POST /v1/detect (Đồng bộ nhanh)**: Latency P99 **< 50ms**. Hệ thống tiếp nhận yêu cầu, đẩy mảng tín hiệu vào hàng đợi xử lý ngầm (Background Task) và lập tức trả về `202 Accepted` kèm `audit_id`.
    *   **GET /v1/status/{audit_id} (Polling nhanh)**: Latency P99 **< 10ms**. Truy vấn trạng thái trực tiếp từ DynamoDB bằng Primary Key.
    *   **Background Processing (Xử lý ngầm)**: Chấp nhận P99 **< 10 giây** cho luồng chạy thuật toán Holt-Winters, phân tích đồ thị NetworkX, gọi mô hình Claude (AWS Bedrock) sinh giải trình và lưu kết quả vào DynamoDB.
    *   **Throughput**: 100 requests/minute cho detect, 300 requests/minute cho polling status.
    *   **Availability**: ≥ 99.5%.
*   **Bảo mật**:
    *   Phân tách multi-tenant nghiêm ngặt: Dữ liệu của tenant này không được rò rỉ sang tenant khác qua việc cách ly context trên từng request API.
    *   Không lưu trữ thông tin nhận dạng cá nhân (PII) như email, tên nhân viên trong prompt gửi lên LLM.

---

## 7. Open questions (Đã chốt phương án từ họp Discovery T2)

*   **Q1: Thời gian trễ CUR của tài khoản AWS Client thực tế là bao lâu?**
    *   *Chốt*: Giả định AWS CUR có độ trễ tự nhiên từ 8-12 tiếng. Do đó, chu kỳ phân tích 24h hàng ngày sẽ lấy dữ liệu của ngày hôm trước ($T-1$) để phân tích chuỗi thời gian, đảm bảo dữ liệu hóa đơn đã cập nhật đầy đủ và giảm thiểu False Positive. Điều này củng cố tính thực tiễn của Timeframe Goal 24h.
*   **Q2: Client đã bật tính năng Cost Allocation Tags trên AWS chưa?**
    *   *Chốt*: Client đã bật nhưng mức độ tuân thủ của các squad chỉ đạt 70%. CDO sẽ bổ sung quét tài nguyên thiếu tag định kỳ và AI Engine sẽ gắn nhãn `"unallocated-unmapped"` hoặc `"service-level-aggregate"` kèm `fallback_context` cho các phần chi tiêu không xác định được resource_id cụ thể.
*   **Q3: Whitelist cứng miễn trừ Auto-containment?**
    *   *Chốt*: Bổ sung quy tắc Whitelist cứng trong code AI Engine: Nếu bất kỳ tài nguyên nào có thẻ tag `FinOps_Bypass = True`, AI Engine bắt buộc phải ghi đè hành động đề xuất thành `ALERT_ONLY` bất kể mức độ nghiêm trọng của chi phí tăng vọt. Đây là chốt chặn để bảo vệ các cụm tài nguyên đặc thù của Core Team không bao giờ bị tắt tự động.
*   **Q4: Thời gian sống (TTL) và Định dạng của Khóa Idempotency?**
    *   *Chốt*: Khóa Idempotency lưu trữ tại DynamoDB có TTL là 24 giờ để tự động bay màu khỏi Database. Đồng thời, ép CDO phải sinh Key theo định dạng Time-bounded Composite Key: `[tenant_id]_[billing_period_YYYYMMDD]_[batch_sequence_id]`. Nếu lỗi looping logic lặp lại sang ngày hôm sau, Key buộc phải đổi ngày mới, tránh ghi đè dữ liệu lịch sử.
