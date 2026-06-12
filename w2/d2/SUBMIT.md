# SUBMIT

## 1. Top-1 confidence và threshold auto-rollback

Top-1 confidence của cluster lớn nhất `c-001-000` là `0.90`, root cause được chọn là `payment-svc`, class là `connection_pool_exhaustion`.

Nếu phải đặt threshold cho auto-rollback không cần SRE confirm, tôi chọn `>= 0.95`. Lý do là auto-rollback có rủi ro cao: nếu RCA sai, rollback có thể làm incident nặng hơn hoặc che mất nguyên nhân thật. Với confidence quanh `0.75-0.90`, hệ thống nên recommend action và đưa bằng chứng cho SRE kiểm tra trước. Ở output hiện tại, `0.90` đủ để ưu tiên điều tra payment-svc đầu tiên, nhưng chưa đủ an toàn để rollback tự động.

## 2. Variant đã chọn

Tôi chọn variant A: rule-based / retrieval-only. Pipeline dùng service graph, timestamp scoring và kNN-style retrieval từ `incidents_history.json`, không cần LLM hay API key. Cách này ổn định, dễ debug, chạy offline được và phù hợp với default path của lab.

Trade-off là pipeline phụ thuộc nhiều vào chất lượng service graph và incident history. Nếu history thiếu case tương tự, classifier có thể trả class chưa chính xác. Free/Paid LLM có thể diễn giải linh hoạt hơn, nhưng tốn chi phí, khó kiểm soát hallucination và không cần thiết với dataset nhỏ này.

## 3. Liên hệ BigPanda/Moogsoft style

Pipeline này gần với BigPanda/Moogsoft style vì có alert clustering từ W2-D1, service graph, root cause ranking, incident similarity retrieval và suggested remediation. Với GeekShop là e-commerce platform có nhiều microservice, alert volume cao và topology tương đối ổn định, hướng này hợp lý vì giảm noise và giúp SRE nhìn ngay candidate cần điều tra.

Nếu service graph thay đổi liên tục hoặc thiếu chính xác, pipeline cần bổ sung trace-based topology từ OpenTelemetry, service registry hoặc Kubernetes service discovery. Nếu không, graph scorer có thể gom sai service hoặc chọn nhầm root cause.
