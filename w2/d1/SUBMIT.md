# W2 D1 - Alert Correlator

## Configuration

- `gap_sec = 120`
- `max_hop = 2`
- Fingerprint: `service|metric|severity`

## Why gap_sec = 120?

Incident thường tạo nhiều alert trong thời gian ngắn. 120 giây đủ để gom các alert trong cùng một burst, ví dụ payment latency, checkout downstream error và edge-lb 5xx, nhưng không quá rộng để gom nhầm các incident cách xa nhau.

Nếu `gap_sec = 30`, một incident có alert đến chậm hơn một chút dễ bị tách thành nhiều cluster nhỏ. Nếu `gap_sec = 600`, nhiều incident khác nhau trong 10 phút có thể bị gom nhầm.

## Why max_hop = 2?

Trong microservice, lỗi thường lan sang service upstream/downstream gần nó trong 1-2 bước. Ví dụ:

`payment-svc -> checkout-svc -> edge-lb`

Nếu chọn `max_hop` quá lớn, các service không liên quan như `recommender-svc` có thể bị gom nhầm vào incident chính chỉ vì xuất hiện gần thời gian.

Với graph đầy đủ của đề, backing store như `catalog-db` không được dùng làm cầu nối giữa hai service nếu bản thân store đó không có alert. Ví dụ `recommender-svc` và `search-svc` cùng phụ thuộc `catalog-db`, nhưng khi `catalog-db` không alert thì không nên tự động gom hai service này vào cùng một incident.

## Fingerprint Design

Fingerprint không include `timestamp`, `value`, `host`, hoặc `pod` vì các field này thay đổi mỗi lần alert fire. Nếu include chúng, cùng một loại alert như `payment-svc|latency_p99_ms|crit` nhưng value khác nhau sẽ bị xem là alert mới và dedup không còn hiệu quả.

## Duplicate vs Correlated Alert

Duplicate alert là cùng một alert lặp lại nhiều lần, ví dụ `payment-svc latency crit` fire 5 lần.

Correlated alert là các alert khác nhau nhưng cùng liên quan một incident, ví dụ payment latency, checkout downstream payment error và edge-lb upstream 5xx.

## Missed or Standalone Alert

Nếu có alert đứng riêng như `recommender-svc cpu_utilization warn`, không coi là lỗi. Nó thành cluster size = 1 vì service này không gần `payment-svc` trên topology và không thuộc incident chính.

Trong scenario payment pool exhaustion, nếu `recommender-svc` cũng alert do batch retrain thì không nên gom recommender vào cluster chính. Lý do là recommender không nằm gần payment trên service graph, dù alert cùng thời gian.

## Scalability

Với 10000 alert, phần chậm nhất là `topology_group`, đặc biệt nếu so sánh từng cặp service và tính shortest path nhiều lần.

Cách tối ưu:

- Dedup trước khi topology grouping.
- Group theo service trước.
- Cache shortest path.
- Precompute distance matrix giữa các service.

## Limitation

Limitation lớn nhất của topology grouping là phụ thuộc vào service graph. Nếu graph sai, thiếu dependency hoặc quá cũ, correlation sẽ gom sai hoặc tách sai.

Cách khắc phục:

- Cập nhật graph từ OpenTelemetry traces.
- Đồng bộ với service registry.
- Dùng Kubernetes service discovery.

## Result

Pipeline đã tạo `results/cluster_summary.json` với:

- Input alerts: 20
- Output clusters: 3
- Reduction ratio: 0.85
