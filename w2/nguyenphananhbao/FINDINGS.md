# FINDINGS.md — Câu hỏi phản biện sự cố

Các nhận xét dưới đây dựa trên lần chạy mới nhất của 8 incident `E01` - `E08` trong `audit.jsonl`. Kết quả grader: `Correct: 8/8`, `Forbidden: 0/8`, `Missing: 0/8`.

---

### 1. Hàm tương đồng Layer 2 được chọn, và lý do

Engine dùng **Conditional Weighted Jaccard + Normalized Deviation Similarity**. Điểm tổng hợp gồm:

- alert service: `0.10`
- affected services: `0.10`
- log signatures: `0.35`
- trace signatures: `0.35`
- metric signatures: `0.10`

Log được so bằng Jaccard trên tập chữ ký log. Trace được so bằng Jaccard trên cạnh `(from, to)`, sau đó nhân với độ giống nhau của `error_rate` và `p99_deviation_ratio`. Metric được so bằng key `(service, metric)` và tỉ lệ thay đổi trước/sau incident.

Phương án thay thế đã cân nhắc là fixed-weight cosine hoặc embedding log. Với chỉ khoảng 30 incident lịch sử, embedding dễ quá khớp và khó giải thích. Fixed-weight cũng phạt sai khi history thiếu một modality. Ví dụ `E03` khớp tốt với `INC-2025-08-02` dù history này thiếu `trace_signatures`; nhờ bỏ trọng số trace khỏi mẫu số khi history thiếu trace, `E03` đạt `max_similarity = 0.809` và chọn đúng `rollback_service:esb`.

---

### 2. Outcome-weighted voting thay đổi thứ hạng ứng viên như thế nào

Mỗi neighbor bỏ phiếu theo công thức:

`vote_weight = similarity * outcome_weight`

Trong đó `success = 1.0`, `partial = 0.5`, `failed = -1.0`. Nhờ vậy, hành động từng thành công trên incident tương tự được nâng điểm; hành động chỉ partial hoặc failed bị giảm/âm điểm.

Ví dụ rõ nhất là `E05`. Ba neighbor gần nhất đều là `connection_pool_exhaustion`, nhưng outcome khác nhau:

- `INC-2025-09-05`: similarity `0.293`, outcome `success`, vote `0.293`
- `INC-2026-05-10`: similarity `0.293`, outcome `partial`, vote `0.147`
- `INC-2025-11-08`: similarity `0.285`, outcome `success`, vote `0.285`

Kết quả candidate votes:

- `rollback_service:payment-svc`: `0.724`
- `increase_pool_size:payment-svc`: `0.578`

Nếu chỉ nhìn top similarity thì hai neighbor đầu gần như hòa (`0.293` và `0.293`). Outcome weighting giúp phân biệt vì neighbor partial chỉ đóng góp nửa trọng số. Tuy nhiên `E05` vẫn bị chặn bởi OOD gate do `max_similarity = 0.293 < 0.35`, nên engine chọn `page_oncall`, cũng là accepted action của đề.

---

### 3. EV calculation chi tiết cho một incident

Xét `E03` (memory leak trên `esb`). Sau khi dedupe action trùng trong cùng một historical neighbor, candidate scores là:

- `rollback_service:esb`: `1.283`
- `increase_pool_size:esb`: `0.474`
- `page_oncall`: fallback/historical page candidate

Với `max_similarity = 0.809`, `Score_max = 1.283`:

- `rollback_service`: `P_success = 0.809 * 1.283 / 1.283 = 0.81`
- `increase_pool_size`: `P_success = 0.809 * 0.474 / 1.283 = 0.30`
- `page_oncall`: `P_success = 0.99`

Penalty:

- `rollback_service`: `10 + 2*2 + 5*1 = 19`
- `increase_pool_size`: `1 + 2*0 + 5*1 = 6`
- `page_oncall`: `0 + 70 virtual penalty = 70`

EV formula:

`EV = P_success * (100 - penalty) + (1 - P_success) * (-150 - penalty)`

Kết quả trong audit:

- `rollback_service`: EV `33.25`
- `increase_pool_size`: EV `-81.28`
- `page_oncall`: EV `27.50`

Vì `33.25 > 27.50`, engine chọn `rollback_service` cho `esb`, đúng accepted action.

---

### 4. Khi nào engine leo thang `page_oncall`

Engine leo thang theo hai nhóm lý do.

**OOD gate (`max_similarity < 0.35`)**

- `E04`: `max_similarity = 0.208`, chọn `page_oncall`
- `E05`: `max_similarity = 0.293`, chọn `page_oncall`
- `E08`: `max_similarity = 0.306`, chọn `page_oncall`

Các case này đều đúng ground truth. `E04` chấp nhận `dns_config_rollback` hoặc `page_oncall`; `E05` chấp nhận `rollback_service:payment-svc` hoặc `page_oncall`; `E08` chấp nhận `rollback_service:t24-service` hoặc `page_oncall`. Với `E08`, OOD gate còn tránh auto-rollback sai `bb-edge`.

**EV chọn page dù không OOD**

- `E02`: `max_similarity = 0.615`, candidate lịch sử là `page_oncall`, chọn đúng vì TLS cert rotation là human-only.
- `E06`: `max_similarity = 0.493`, auto candidates có EV âm (`rollback_service = -45.75`, `increase_pool_size = -57.46`), nên `page_oncall` thắng với EV `27.50`.
- `E07`: `max_similarity = 0.577`, có neighbor rate-limit từng page và một rollback yếu; `page_oncall` thắng EV `27.50` so với rollback EV `-24.75`, đúng accepted action OOD/novel của đề.

---

### 5. Dạng incident dễ làm engine lỗi nhất

Dạng dễ làm engine lỗi nhất là **multi-fault cascading incident**: hai lỗi độc lập xảy ra cùng lúc, ví dụ vừa memory leak trên `notification-svc`, vừa slow query trên `catalog-db`.

Lý do: engine hiện chọn một `live_primary` bằng cách đi theo trace anomaly từ alert service và giữ lại service API sâu nhất. Cách này hợp với các incident một root cause, nhưng nếu có hai cụm lỗi độc lập thì engine có thể chỉ chọn một cụm, map action sang một service, rồi bỏ sót cụm còn lại.

Cải tiến cụ thể: tách trace/log anomaly thành nhiều connected components, chạy retrieval + EV riêng cho từng component, rồi trả về một plan nhiều hành động hoặc escalate nếu các component có xung đột. Chưa triển khai vì eval set hiện chỉ yêu cầu một action cuối cùng và 8 incident đều có một quyết định được chấm theo single-action contract.

---

### 6. Giới hạn còn lại

Log parser hiện là substring/template matcher trong `features.py`. Nó đủ để bridge raw log sang historical signatures của lab, nhưng vẫn brittle nếu production đổi format log hoặc xuất hiện service mới. Bản tốt hơn nên dùng Drain/Drain3 hoặc một template clustering offline, rồi so Jaccard trên `template_id` thay vì hard-code substring.
