# W3-D1 Submission — Nguyễn Phan Anh Bảo

## 3 bài học rút ra
1. Hiểu cách quy đổi từ tỷ lệ lỗi thô sang Burn Rate để đồng nhất ngưỡng cảnh báo cho mọi service.
2. Cách kết hợp toán học logic AND giữa cửa sổ dài và cửa sổ ngắn để chuông tự động tắt (Recover) sau 5 phút mà không bị dính đuôi.
3. Không đặt SLO cao hơn năng lực thực tế của Baseline để tránh Cardinality Explosion và sập TSDB.

## 1 vấn đề cần làm rõ
Cách cấu hình tối ưu tài nguyên RAM cho OTel Collector khi phải xử lý Tail-based Sampling với các transaction chạy rất dài.

## 1 điểm đánh đổi (trade-off) trong quyết định SLO cần cân nhắc
Quyết định hạ SLO Target của API xuống 99.0% để phù hợp với baseline thực tế (99.65% availability) và hạ SLO Target của Frontend xuống 98.5% để đạt mốc Noise Reduction 86.4%. Điều này giúp giảm áp lực cho đội ngũ On-call nhưng có thể bỏ sót một số lỗi hoặc trải nghiệm chậm của người dùng ở vùng biên.

## Validation report
- noise_reduction_pct: 86.4%
- mttd_delta_s: 0s
- false_negative: 0
- verdict: pass
