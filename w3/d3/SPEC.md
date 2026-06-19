# AIOps Mini-Platform Spec — Nguyen Phan Anh Bao

## 1. Platform overview
Nền tảng AIOps Mini-Platform được thiết kế để tự động giám sát, phát hiện bất thường và phân tích nguyên nhân gốc (RCA) cho hệ thống vi dịch vụ (microservices) thương mại điện tử chạy trên môi trường Docker. Phạm vi hoạt động bao gồm thu thập dữ liệu chỉ số hiệu năng (Prometheus metrics), nhật ký hoạt động (access logs), tự động gom cụm cảnh báo theo cửa sổ thời gian trượt và đề xuất dịch vụ phát sinh lỗi chính. Đối tượng sử dụng nền tảng là đội ngũ Kỹ sư độ tin cậy hệ thống (SRE) và kỹ sư trực vận hành (On-call) nhằm giảm thời gian khôi phục dịch vụ (MTTR).

## 2. SLO definition (from W3-D1)
Cấu hình chỉ số độ tin cậy (SLO) cho 3 dịch vụ cốt lõi:

*   **API Service (`api`)**:
    *   **SLI Availability**: `count(2xx,3xx,4xx_not_429 AND latency<500ms) / count(all)`
    *   **Target SLO**: 99.0% (30-day window)
    *   **Error Budget**: 207,378 allowed failures/month (equivalent to 432 minutes of downtime)
*   **Database Service (`db`)**:
    *   **SLI Latency**: `count(success AND duration<100ms) / count(all)`
    *   **Target SLO**: 99.5% (30-day window)
    *   **Error Budget**: 8,632 allowed failures/month (equivalent to 216 minutes of downtime)
*   **Frontend Service (`frontend`)**:
    *   **SLI Availability**: `count(dom_ready<3000 AND no_js_err AND no_net_err) / count(all)`
    *   **Target SLO**: 98.5% (30-day window)
    *   **Error Budget**: 77,760 allowed failures/month (equivalent to 648 minutes of downtime)

## 3. Detection + Correlation + RCA stack (from W1+W2)
*   **Detector:** Sử dụng Prometheus rule để truy vấn thời gian thực chỉ số trạng thái `up`, tỷ lệ lỗi HTTP 5xx (`http_requests_total`) và thời gian phản hồi p99 (`http_request_duration_seconds`). Hệ thống cảnh báo tự động gửi thông tin dị thường dưới dạng JSON payload. (Tham khảo nâng cấp tại [ADR-001](file:///d:/Xbrain/aiops-nguyenphananhbao/w3/d3/ADR.md) để hỗ trợ phát hiện CPU saturation).
*   **Correlator:** Áp dụng thuật toán gom cụm cảnh báo trong cửa sổ thời gian trượt (Time-window clustering, mặc định 120 giây) để lọc nhiễu và gom các cảnh báo có cùng thời gian phát sinh vào một cụm sự cố duy nhất (`cluster_id`).
*   **RCA:** Sử dụng thuật toán duyệt đồ thị Dependency-aware dựa trên Service Dependency Graph tĩnh để định vị dịch vụ hạ nguồn bị lỗi sâu nhất. Tích hợp luật loại trừ bão thử lại (Retry Storm) cho `checkout-svc` để cải thiện độ chính xác.

## 4. Reliability validation (from W3-D2)
*   **Chaos run cadence:** Monthly (Hàng tháng)
*   **Detected/total ratio target:** 80.0%
*   **Steady-state signal:** Synthetic probe (gửi request mỗi 5 giây) kết hợp giám sát Access logs.

### Scoreboard từ Chaos Report (W3-D2):
```text
==== Chaos Run ====
Total: 10
Detected: 8/10
RCA correct: 7/8
False alarms in baseline windows: 0
Precision: 1.0000
Recall: 0.8000
MTTD p50: 15.0s, p95: 21s
```

### Top 3 Gaps:
1.  **Vòng lặp phụ thuộc giám sát (Monitoring Dependency Loop):** Khi đĩa của `log-collector` đầy, log không được chuyển về và AI bị mù thông tin.
2.  **Nhầm lẫn do bão thử lại (Retry Storm Confusion):** Lỗi ở dịch vụ thanh toán làm tăng lỗi thử lại ở `checkout-svc`, đánh lừa RCA chọn nhầm checkout làm root cause.
3.  **Dị thường bị che khuất dưới nhiễu nền (Noise Floor Masking):** Trễ phân giải DNS quá nhỏ bị chìm dưới các dao động thông thường và không kích hoạt cảnh báo.

## 5. Operational pattern (from W3-D3)
*   **Reproduced outage:** Cloudflare WAF Regex Catastrophic Backtracking (2019-07-02)
*   **Key learning:**
    1.  Pipeline giám sát bị mù hoàn toàn trước các sự cố CPU-bound nếu dịch vụ không sụp đổ hẳn mà chỉ bị treo (do thiếu giám sát tài nguyên CPU của Docker container).
    2.  Khi container bị treo do CPU 100%, Prometheus Scrape bị timeout dẫn đến mất hoàn toàn metrics (lỗi missing data). Cần triển khai cơ chế Dead-man's switch phát hiện Scrape Failure.
*   **ADR Reference:** Quyết định nâng cấp detector sang mô hình Ensemble Anomaly Detector kết hợp giám sát CPU & Scrape State được ghi nhận chi tiết tại [ADR-001.md](file:///d:/Xbrain/aiops-nguyenphananhbao/w3/d3/ADR.md).

## 6. Cost model (from W3-D3)
Cấu hình chi phí cho stack hiện tại (14 services):
*   **Số lượng service:** 14
*   **Số lượng sự cố/tháng:** 4
*   **Thời gian xử lý trung bình:** 1.0 giờ
*   **Chi phí downtime/giờ:** $30,000
*   **Chi phí vận hành AIOps/tháng:** $15,000
*   **Tỷ lệ giảm MTTR dự kiến:** 40%

### Kết quả tính toán từ `cost_model.py`:
```json
{
  "monthly_value": 48000.0,
  "monthly_cost": 15000.0,
  "roi": 3.2,
  "payback_months": 0.3125,
  "verdict": "worth_it"
}
```
*   **Break-even point:** Hệ thống đạt điểm hòa vốn khi số lượng sự cố tránh được hoặc được giảm thiểu đạt tối thiểu **1.25 sự cố/tháng**.

## 7. Open risks
*   **Risk 1 (Model Drift):** Các mô hình phát hiện bất thường Ensemble bị giảm độ chính xác theo thời gian khi hành vi tải hệ thống thay đổi.
    *   *Severity:* Medium
    *   *Mitigation:* Thiết lập quy trình tự động cập nhật và huấn luyện lại mô hình (retraining) hàng tuần sử dụng dữ liệu tuần gần nhất.
*   **Risk 2 (Alert Fatigue):** Quá nhiều cảnh báo giả do nhiễu mạng hoặc tải tăng đột biến tạm thời (transient anomalies).
    *   *Severity:* Low
    *   *Mitigation:* Thiết lập cấu hình bộ lọc thời gian duy trì dị thường (persistence filter) tối thiểu 3 chu kỳ scrape trước khi gửi alert.
*   **Risk 3 (Monitoring Cascade Failure):** Pipeline giám sát nằm chung cụm hạ tầng với production bị ảnh hưởng lây lan khi xảy ra sự cố nghẽn mạng lớn.
    *   *Severity:* High
    *   *Mitigation:* Tách biệt hoàn toàn hạ tầng chạy Prometheus và AIOps Pipeline sang một cluster quản lý độc lập (out-of-band monitoring infrastructure).
