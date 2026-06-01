# Tuần 1 Ngày A - Bài nộp phát hiện bất thường

## Các file cần nộp

- `assignment.ipynb`: notebook có EDA, bộ phát hiện, tinh chỉnh tham số, đánh giá, vẽ kết quả và nhận xét ngắn.
- `isolation_forest_model.joblib`: model Isolation Forest đã train kèm danh sách đặc trưng.
- `knowledge_check.png`: ảnh trả lời ngắn phần kiểm tra kiến thức.
- `data/machine_temperature_system_failure.csv`: bộ dữ liệu NAB thuộc nhóm `realKnownCause`.

## Bộ dữ liệu

Bộ dữ liệu sử dụng: NAB `realKnownCause/machine_temperature_system_failure.csv`.

- Số dòng: 22,695
- Khoảng thời gian: từ `2013-12-02 21:15:00` đến `2014-02-19 15:25:00`
- Mean: `85.926`
- Std: `13.747`
- Min: `2.085`
- Max: `108.511`
- Skewness: `-1.834`
- Nhãn đúng có 4 mốc thời gian anomaly từ NAB. Khi tính metric theo từng điểm, em đánh dấu vùng +/- 1 giờ quanh mỗi mốc thời gian là anomaly.

## Cách tránh data leakage

Dữ liệu được chia theo thời gian, không shuffle:

- Train: 60% đầu chuỗi, dùng để fit detector.
- Validation: 20% tiếp theo, dùng để tune tham số.
- Test: 20% cuối chuỗi, chỉ dùng để báo cáo kết quả cuối cùng.

Bộ phát hiện thống kê IQR chỉ fit `Q1`, `Q3`, `IQR` trên train; hệ số IQR được tune trên validation. Isolation Forest chỉ fit trên train để tune `contamination`, sau đó fit lại bằng train + validation với contamination tốt nhất. Không dùng thông tin của test để train hoặc chọn tham số.

## Kết luận EDA

Dữ liệu bị lệch trái khá mạnh vì skewness âm lớn. Biểu đồ ACF có đỉnh lặp lại quanh lag 288, tương ứng chu kỳ ngày do dữ liệu lấy mẫu mỗi 5 phút. Vì vậy dữ liệu có tính seasonal và không nên giả định là stationary hoàn toàn. Vì phân phối skew mạnh, detector thống kê được chọn là IQR. Isolation Forest được dùng để học anomaly theo ngữ cảnh từ nhiều đặc trưng.

## Detector đã dùng

Bộ phát hiện thống kê: IQR fit trên train, tune hệ số IQR trên validation, sau đó áp dụng sang test.

Các đặc trưng của Isolation Forest:

- `value`
- `rolling_mean`
- `rolling_std`
- `rate_of_change`
- `lag_1`
- `lag_60`
- `hour`
- `day_of_week`
- `z_score`

## Tuning IQR trên validation

| Hệ số IQR | Precision_validation | Recall_validation | F1_validation | Cảnh báo sai_validation |
| --- | --- | --- | --- | --- |
| 1.5 | 0.027 | 1.000 | 0.052 | 912 |
| 2.0 | 0.036 | 1.000 | 0.070 | 669 |
| 2.5 | 0.062 | 1.000 | 0.117 | 377 |
| 3.0 | 0.100 | 0.760 | 0.177 | 171 |

## Tuning Isolation Forest trên validation

| contamination | Precision_validation | Recall_validation | F1_validation | Cảnh báo sai_validation |
| --- | --- | --- | --- | --- |
| 0.010 | 0.000 | 0.000 | 0.000 | 71 |
| 0.020 | 0.006 | 0.040 | 0.010 | 171 |
| 0.050 | 0.044 | 0.800 | 0.084 | 431 |

## So sánh cuối cùng trên test

| Chỉ số | Thống kê IQR | Isolation Forest |
| --- | --- | --- |
| Precision | 0.049 | 0.045 |
| Recall | 1.000 | 1.000 |
| F1 | 0.093 | 0.086 |
| Cảnh báo sai | 487 | 534 |

## Nhận xét ngắn

Bộ phát hiện thống kê IQR tốt hơn trong lần chạy này vì F1 test cao hơn và cảnh báo sai ít hơn Isolation Forest. IQR phù hợp vì anomaly trong test có dạng giá trị nhiệt độ lệch mạnh. Isolation Forest vẫn hữu ích để theo dõi anomaly theo ngữ cảnh, nhưng với dataset này nó tạo nhiều cảnh báo sai hơn.

Nếu đưa vào production, em sẽ chọn IQR đã tune hệ số trên validation làm baseline chính vì đơn giản, dễ giải thích và có F1 test tốt hơn. Em vẫn giữ Isolation Forest như detector phụ để so sánh khi dữ liệu có pattern phức tạp hơn.
