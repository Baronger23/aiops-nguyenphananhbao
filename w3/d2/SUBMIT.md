# W3-D2 Submission — Nguyen Phan Anh Bao

## 3 bài học kinh nghiệm rút ra về AIOps pipeline

1.  **Vòng lặp phụ thuộc giám sát (Monitoring Dependency Loop)**: Việc thiết kế AIOps Pipeline phụ thuộc trực tiếp vào log được thu thập bởi chính container đích (`log-collector`) là một điểm yếu lớn. Khi ổ đĩa của `log-collector` bị đầy, dữ liệu log không thể truyền đi, dẫn đến việc pipeline bị mất nguồn cấp thông tin (bị "mù" hoàn toàn).
2.  **Ảnh hưởng của Bão Thử lại (Retry Storm)**: Các cơ chế tự động thử lại (Retry) của client khi gặp lỗi mạng/ứng dụng (như HTTP 500 ở `checkout-svc`) sẽ làm trầm trọng thêm vấn đề của hệ thống và tạo ra bão Alert giả ở tầng Edge, gây nhiễu loạn cho các thuật toán phân tích nguyên nhân gốc (RCA) đơn giản.
3.  **Tầm quan trọng của Lưới an toàn (Safety Net)**: Để chạy Chaos Engineering an toàn trong môi trường Staging/Production, bắt buộc phải có một Steady-State Probe độc lập chạy ngầm để giám sát liên tục trải nghiệm người dùng cuối và kích hoạt Rollback tự động khi chỉ số chất lượng dịch vụ (SLO) bị vi phạm.

---

## 1 dị thường kỳ vọng được phát hiện nhưng bị bỏ lọt

*   **Thí nghiệm (Experiment)**: Ca số 7 - `log_collector_disk` (Đầy ổ cứng bộ thu thập log).
*   **Lý do kỳ vọng hệ thống phát hiện dị thường (Why detection was expected)**: Ổ đĩa bị đầy 95% là một bất thường tài nguyên vật lý rất rõ ràng ở mức hạ tầng, cần phải kích hoạt cảnh báo Prometheus ngay lập tức.
*   **Nguyên nhân pipeline bỏ lọt (Why pipeline missed - Hypothesis)**: Do toàn bộ kênh dẫn truyền cảnh báo và log từ dịch vụ bị ngắt nghẽn cự ly truyền do ổ cứng bị đầy (không thể ghi tiếp log). AIOps Pipeline rơi vào trạng thái đói dữ liệu (data starvation) nên ghi nhận hệ thống vẫn bình thường.

---

## 1 đánh đổi trong thiết kế pipeline cần xem xét lại

*   **Đánh đổi giữa Tốc độ phát hiện và Nhiễu động (MTTD vs False Positive Rate)**: Cấu hình Alertmanager và Prometheus scrape interval quá ngắn (ví dụ: 5-10 giây) giúp giảm thời gian phát hiện lỗi (MTTD) xuống rất thấp, nhưng lại dễ bị tác động bởi các biến động tài nguyên tạm thời (nhiễu nền), dẫn đến cảnh báo giả (False Positives). 
*   **Hướng cải tiến đề xuất**: Xem xét lại việc sử dụng ngưỡng động dạng tích lũy (Cumulative/Exponential Moving Average) thay vì ngưỡng tĩnh đơn giản để lọc bớt nhiễu tài nguyên.

---

## Scoreboard summary

*   **detected**: 8/10
*   **rca_correct**: 7/8
*   **mttd_p50**: 15s
*   **false_alarms**: 0
*   **verdict**: PASS (Recall: 80% >= 70%, RCA Accuracy: 87.5% >= 70%, False Alarms: 0 <= 1)
