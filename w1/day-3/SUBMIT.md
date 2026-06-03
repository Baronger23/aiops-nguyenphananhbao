# Bài nộp Day 3: AIOps Data Layer

## 1. Sơ đồ kiến trúc

![Sơ đồ kiến trúc](architecture.png)

Tình huống sử dụng: phát hiện bất thường trên `payment-service`.

Luồng xử lý: Payment Service -> OpenTelemetry SDK -> OTel Collector/Fluent Bit -> Kafka -> Flink -> VictoriaMetrics/Loki/S3 -> Grafana/Python anomaly detector -> PagerDuty.

## 2. Ước tính chi phí

```text
Chạy: uv run python cost_model.py
```

| Quy mô | Số service | Log/ngày | Metric EPS | Lưu trữ | Tính toán | Mạng | Tổng self-host | Tổng Datadog |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Small | 10 | 50 GB | 100,000 | $235.98 | $475.00 | $50.74 | $761.72 | $904.92 |
| Medium | 100 | 500 GB | 1,000,000 | $2,359.80 | $4,750.00 | $507.36 | $7,617.16 | $9,049.20 |
| Large | 1000 | 5120 GB | 10,000,000 | $23,760.00 | $47,632.00 | $5,145.60 | $76,537.60 | $91,392.00 |

## 3. Tóm tắt ADR

ADR-001 chọn Kafka thay vì direct push cho lớp vận chuyển telemetry. Kafka làm tăng chi phí broker và thêm khoảng 100-300 ms độ trễ, nhưng đổi lại có durable buffering, replay, cô lập consumer và scale an toàn hơn cho mức 1M-10M metric events/giây. Direct push đơn giản và rẻ hơn cho hệ thống rất nhỏ, nhưng có rủi ro overload hoặc mất dữ liệu khi storage/stream processor bị suy giảm.

## 4. Nhận xét

Với startup Series A có khoảng 50 service, tôi sẽ khuyến nghị buy trước, ví dụ dùng Datadog hoặc Grafana Cloud. Team cần time-to-value nhanh, alerting đáng tin cậy và ít hệ thống phải tự vận hành. Chạy Kafka, Flink, VictoriaMetrics, Loki và retention trên S3 một cách đúng đắn cần platform maturity, on-call runbook, capacity planning và failure testing.

Chiến lược tốt hơn là bắt đầu bằng SaaS cho observability, định nghĩa instrumentation bằng OpenTelemetry ngay từ đầu, và giữ tùy chọn chuyển metric/log volume cao sang self-host hoặc hybrid stack sau này. Ở mức 50 service, sự tập trung của engineering team thường đáng giá hơn phần tiết kiệm chi phí hạ tầng.
