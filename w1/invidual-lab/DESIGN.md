# Detection Approach - DESIGN.md

## Approach tôi dùng

Tôi dùng một hybrid streaming detector:

- Metric-level detector sinh tín hiệu bất thường từ từng metric.
- Fault-level scoring gom các tín hiệu để quyết định loại lỗi.
- Log chỉ dùng như bằng chứng phụ, không alert riêng chỉ vì có log `ERROR`.

Cách này tránh kiểu quá thô như `if metric > threshold then alert`, nhưng vẫn dễ giải thích và chạy realtime.

## Tại sao chọn approach này

Bảng metric của đề đã cho khoảng bình thường khá rõ, nên tôi dùng static baseline làm ngưỡng ban đầu. Tuy nhiên stream có noise và một số metric như request/sec có thể thay đổi theo thời gian, nên pipeline thêm EWMA, rolling z-score, IQR outlier và rolling slope để phát hiện bất thường động.

Bài không chỉ yêu cầu phát hiện "có anomaly", mà còn cần phân loại lỗi thành:

- `memory_leak`
- `traffic_spike`
- `dependency_timeout`

Vì vậy detector chạy ở metric-level, còn alert được quyết định ở fault-level bằng scoring.

## Cách hoạt động

Mỗi payload gửi vào `/ingest`, pipeline trích metrics thành các tín hiệu chuẩn hóa:

- `memory_pct`
- `cpu_usage_percent`
- `http_requests_per_sec`
- `http_p99_latency_ms`
- `http_5xx_rate`
- `jvm_gc_pause_ms_avg`
- `queue_depth`
- `upstream_timeout_rate`

Với mỗi metric, pipeline kiểm tra nhiều detector:

- `soft_threshold`: vượt ngưỡng bất thường dựa trên bảng baseline.
- `hard_threshold`: vượt ngưỡng nghiêm trọng.
- `rolling_z`: giá trị hiện tại lớn hơn mean của window gần đây cộng 3 standard deviations.
- `iqr_outlier`: giá trị hiện tại lớn hơn `Q3 + 1.5 * IQR`.
- `ewma_deviation`: giá trị lệch mạnh so với EWMA baseline.
- `rolling_slope` / `ewma_trend`: dùng cho memory leak để bắt xu hướng tăng dần.

Sau đó pipeline gom signal theo từng loại fault.

### `memory_leak`

Các evidence chính:

- Memory percent tăng bất thường.
- Memory có slope/trend tăng.
- GC pause bất thường.
- Log có keyword liên quan memory/heap/GC.

### `traffic_spike`

Các evidence chính:

- Request/sec bất thường.
- Queue depth bất thường.
- Latency bất thường.
- CPU tăng.
- Log có keyword overloaded/rejected/queue depth high.

### `dependency_timeout`

Các evidence chính:

- Upstream timeout rate bất thường.
- 5xx rate bất thường.
- Latency bất thường.
- Log có keyword circuit breaker/upstream timeout.

Nếu fault đạt `min_score` và xuất hiện trong 2 payload liên tiếp, pipeline ghi alert vào `alerts.jsonl`.

## Parameters tôi chọn

- Window size: `12` datapoints. Với generator mặc định 1 POST mỗi 3 giây, window này khoảng 36 giây realtime.
- EWMA alpha: `0.25`, đủ nhạy với thay đổi mới nhưng không bị nhiễu bởi 1 tick lẻ.
- Consecutive hits: `2`, giảm false alert do noise.
- Min score mỗi fault: `3`, yêu cầu ít nhất 3 evidence metric/log trước khi alert.

Static baseline lấy từ bảng metric của đề:

- Memory normal khoảng 800MB / 2GB limit, soft khi utilization cao hơn `65%`.
- CPU soft khi trên `65%`.
- RPS soft khi trên `250 req/s`.
- Latency soft khi trên `250ms`.
- 5xx soft khi trên `3%`.
- GC soft khi trên `45ms`.
- Queue depth soft khi trên `35`.
- Upstream timeout soft khi trên `4%`.

## Cách xử lý log

Logs là evidence phụ. Pipeline phân tích:

- `error_signal`: log level `ERROR` hoặc `FATAL`.
- `warning_signal`: log level `WARN`.
- `memory_keywords`: `outofmemory`, `heap`, `gc pause`, `oom`.
- `traffic_keywords`: `queue depth high`, `overloaded`, `rejected`.
- `dependency_keywords`: `upstream timeout`, `circuit breaker`, `connection refused`, `503`.

Pipeline không alert chỉ vì có error log. Log chỉ cộng điểm khi metric cũng đang có signal bất thường.

## Cải thiện nếu có thêm thời gian

Có thể thêm replay test từ JSONL, đo time-to-detect, hiển thị score chi tiết trong alert và dùng baseline riêng theo từng giờ trong ngày cho traffic để giảm false positive hơn nữa.
