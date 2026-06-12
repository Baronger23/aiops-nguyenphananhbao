# FINDINGS

Cluster chính `c-001-000` được RCA chọn `payment-svc` là root cause. Lý do là `payment-svc` nằm sâu hơn trong dependency chain so với `checkout-svc` và `edge-lb`, đồng thời các alert đầu tiên trong cluster cũng xuất hiện ở payment trước khi lan lên checkout và edge. Các service như `checkout-svc`, `edge-lb`, `cart-svc`, và `notification-svc` nhiều khả năng là victim hoặc propagation signal từ incident payment. Confidence của cluster chính là `0.90`, đủ cao để ưu tiên điều tra payment trước, nhưng vẫn nên để SRE xác nhận trước khi auto-remediation như rollback production.

Hai cluster còn lại là standalone: `recommender-svc` và `search-svc`. Với `recommender-svc`, history retrieval map sang class `batch_job_contention`, phù hợp với batch retrain hoặc workload ML chạy độc lập. Với `search-svc`, pipeline map sang `cache_warmup`, vì alert đứng riêng và top similar incident gần nhất là search index cold cache. Một case chưa chắc chắn là khi backing store như `catalog-db` hoặc `payments-db` cũng alert cùng lúc. Khi đó store có thể là culprit thật, nhưng cũng có thể chỉ là victim do application leak connection hoặc retry storm.

Tôi không chọn bonus LLM vì dataset nhỏ, gồm 20 alerts và 30 incident history. Rule-based graph scoring kết hợp retrieval/kNN đã đủ để tạo root cause candidate, class, action, confidence và reasoning ổn định mà không cần API key.
