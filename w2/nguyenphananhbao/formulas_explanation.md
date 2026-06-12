# Hướng dẫn Công thức Toán học & Ví dụ Thực tế

Tài liệu này giải thích chi tiết các công thức toán học được sử dụng trong Động cơ Khắc phục Sự cố Tự động (Remediation Engine) và cung cấp một ví dụ tính toán từng bước bằng số liệu thực tế.

---

## 1. Công thức Layer 2: Retrieval & Voting

### 1.1. Hàm tương đồng động (Conditional Weighted Similarity)
Điểm tương đồng tổng thể $Sim(q, h)$ giữa live incident $q$ và incident lịch sử $h$ được tính bằng trung bình có trọng số động của các đặc trưng:

$$Sim(q, h) = \frac{w_{\text{alert}} S_{\text{alert}} + w_{\text{affected}} S_{\text{affected}} + w_{\text{log}} S_{\text{log}} + w_{\text{trace}} S_{\text{trace}} + w_{\text{metric}} S_{\text{metric}}}{w_{\text{alert}} + w_{\text{affected}} + w_{\text{log}} + w_{\text{trace}} + w_{\text{metric}}}$$

**Trọng số mặc định**:
*   $w_{\text{alert}} = 0.10$
*   $w_{\text{affected}} = 0.10$
*   $w_{\text{log}} = 0.35$
*   $w_{\text{trace}} = 0.35$
*   $w_{\text{metric}} = 0.10$

> [!NOTE]
> **Chuẩn hóa trọng số động (Conditional Weighting)**:
> Nếu sự cố lịch sử $h$ bị thiếu thông tin đặc trưng (ví dụ: không có metric hoặc trace signatures), trọng số tương ứng $w_i$ của đặc trưng đó ở mẫu số sẽ được gán bằng $0.0$ để tránh phạt điểm tương đồng tổng thể một cách oan uổng.

#### Các chỉ số tương đồng thành phần ($S_i$):

#### A. Tương đồng Cảnh báo ($S_{\text{alert}}$)
Đo lường sự trùng khớp của dịch vụ bắn cảnh báo (`alert_service`) từ live incident so với tập các dịch vụ bị ảnh hưởng lịch sử ($H_{\text{affected}}$) đã qua ánh xạ tên tương đương:
$$S_{\text{alert}} = \begin{cases} 1.0 & \text{nếu } \text{alert\_service}_{live} \in H_{\text{affected\_mapped}} \\ 0.0 & \text{ngược lại} \end{cases}$$

#### B. Tương đồng Dịch vụ ảnh hưởng ($S_{\text{affected}}$)
So sánh mức độ tương quan của phạm vi ảnh hưởng thông qua chỉ số Jaccard giữa tập dịch vụ bị ảnh hưởng của live incident ($Q_{\text{aff}}$) và lịch sử đã ánh xạ ($H_{\text{aff}}$):
$$S_{\text{affected}} = \frac{|Q_{\text{aff}} \cap H_{\text{aff}}|}{|Q_{\text{aff}} \cup H_{\text{aff}}|}$$
*(Nếu cả hai tập đều rỗng, $S_{\text{affected}} = 1.0$. Nếu một trong hai tập rỗng, $S_{\text{affected}} = 0.0$)*

#### C. Tương đồng Chữ ký Log ($S_{\text{log}}$)
Độ tương đồng Jaccard giữa tập chữ ký log lỗi trích xuất từ live incident ($Q_{\text{log}}$) và lịch sử ($H_{\text{log}}$):
$$S_{\text{log}} = \frac{|Q_{\text{log}} \cap H_{\text{log}}|}{|Q_{\text{log}} \cup H_{\text{log}}|}$$
*(Nếu lịch sử không ghi nhận chữ ký log nào, hệ thống gán $w_{\text{log}} = 0.0$ ở công thức tổng và bỏ qua đặc trưng này)*

#### D. Tương đồng Trace ($S_{\text{trace}}$)
Kết hợp giữa sự trùng khớp cấu trúc kết nối đồ thị (cạnh kết nối gửi-nhận `(from, to)`) và độ lệch số liệu hiệu năng (tỷ lệ lỗi và độ lệch latency P99) trên các cạnh trùng nhau.

Gọi $Q_{\text{edges}}$ là tập cạnh lỗi của live incident, $H_{\text{edges}}$ là tập cạnh lỗi của lịch sử đã ánh xạ tên.
Nếu tồn tại các cạnh giao nhau $Edges_{\text{intersect}} = Q_{\text{edges}} \cap H_{\text{edges}}$:
*   **Tương đồng tỷ lệ lỗi (Error Rate Similarity)** của cạnh $e$:
    $$Sim_{\text{error}}(e) = \max(0.0, 1.0 - |qe.\text{error\_rate} - he.\text{error\_rate}|)$$
    
    > [!NOTE]
    > **Tại sao tỷ lệ lỗi dùng hiệu số tuyệt đối thay vì chia tỷ lệ?**:
    > 1. **Đã được chuẩn hóa sẵn**: Tỷ lệ lỗi (`error_rate`) theo định nghĩa vốn dĩ đã là một đại lượng chuẩn hóa nằm trong đoạn cố định $[0, 1]$ (từ $0\%$ đến $100\%$), không bị vô hạn (unbounded) giống như độ lệch latency.
    > 2. **Tránh bóp méo khi lỗi rất nhỏ**: Nếu chia tỷ lệ đối xứng, hai mức lỗi nhỏ như $0.5\%$ và $1.5\%$ (đều rất nhỏ, hầu như không lỗi) sẽ bị tính sai số lớn ($\frac{|0.005-0.015|}{0.02} = 0.5 \rightarrow Sim = 0.5$). Trong khi hiệu tuyệt đối phản ánh đúng tính chất tương đồng của chúng ($1.0 - |0.005-0.015| = 0.99$).
*   **Tương đồng độ lệch latency P99 (Latency Deviation Similarity)** của cạnh $e$ với $qd = qe.\text{p99\_deviation\_ratio}$ và $hd = he.\text{p99\_deviation\_ratio}$:
    $$Sim_{\text{dev}}(e) = \max\left(0.0, 1.0 - \frac{|qd - hd|}{qd + hd}\right)$$
    
    > [!NOTE]
    > **Giải thích tỷ lệ $\frac{|qd - hd|}{qd + hd}$**:
    > Đây là công thức tính **Độ lệch chuẩn hóa đối xứng (Symmetric Normalized Difference)**:
    > 1. Phép trừ $|qd - hd|$ ở tử số đo lường khoảng cách tuyệt đối.
    > 2. Phép chia cho tổng $(qd + hd)$ ở mẫu số giúp chuẩn hóa khoảng cách này về dạng tỷ lệ phần trăm (phạm vi $[0, 1]$) để tránh bị ảnh hưởng bởi thang đo (scale) của giá trị trễ. Ví dụ: Sự khác biệt giữa độ lệch trễ 10.0 lần và 10.2 lần sẽ có điểm tương đồng rất cao vì tỷ lệ lệch rất nhỏ ($\frac{0.2}{20.2} \approx 0.01$), trong khi lệch giữa 1.2 lần và 1.4 lần sẽ có điểm tương đồng thấp hơn vì tỷ lệ lệch lớn hơn ($\frac{0.2}{2.6} \approx 0.08$).
    > 3. Lấy $1.0$ trừ đi tỷ lệ này để chuyển đổi từ **Khoảng cách/Sai số** (càng nhỏ càng tốt) sang **Độ tương đồng** (càng lớn càng tốt).
*   **Tương đồng tổng hợp trên cạnh $e$**:
    $$Sim_{\text{edge}}(e) = 0.5 \cdot Sim_{\text{error}}(e) + 0.5 \cdot Sim_{\text{dev}}(e)$$

**Điểm tương đồng Trace tổng thể ($S_{\text{trace}}$)**:
$$S_{\text{trace}} = \frac{|Q_{\text{edges}} \cap H_{\text{edges}}|}{|Q_{\text{edges}} \cup H_{\text{edges}}|} \times \left( \frac{1}{|Edges_{\text{intersect}}|} \sum_{e \in Edges_{\text{intersect}}} Sim_{\text{edge}}(e) \right)$$
*(Nếu không có cạnh giao nhau nào, $S_{\text{trace}} = 0.0$. Nếu lịch sử không có trace signature, gán $w_{\text{trace}} = 0.0$)*

> [!TIP]
> **Ví dụ tính điểm tương đồng Trace ($S_{\text{trace}}$) từng bước**:
> Giả sử hệ thống trích xuất dữ liệu của live incident và một sự cố lịch sử như sau:
> *   **Query Incident ($Q$)**: Có 2 cạnh trace lỗi:
>     1.  `edge-lb -> payment-svc` (tỷ lệ lỗi $err_q = 0.10$, latency dev $dev_q = 3.0$)
>     2.  `payment-svc -> payment-db` (tỷ lệ lỗi $err_q = 0.05$, latency dev $dev_q = 1.5$)
>     *Tập cạnh $Q_{\text{edges}} = \{(\text{edge-lb}, \text{payment-svc}), (\text{payment-svc}, \text{payment-db})\}$*
> *   **History Incident ($H$)**: Có 2 cạnh trace lỗi:
>     1.  `edge-lb -> payment-svc` (tỷ lệ lỗi $err_h = 0.12$, latency dev $dev_h = 2.8$)
>     2.  `payment-svc -> auth-svc` (tỷ lệ lỗi $err_h = 0.20$, latency dev $dev_h = 4.0$)
>     *Tập cạnh $H_{\text{edges}} = \{(\text{edge-lb}, \text{payment-svc}), (\text{payment-svc}, \text{auth-svc})\}$*
>
> **Bước 1: Tính tương đồng Jaccard cấu trúc đồ thị**
> *   Phần giao: $Q_{\text{edges}} \cap H_{\text{edges}} = \{(\text{edge-lb}, \text{payment-svc})\} \rightarrow |Q \cap H| = 1$
> *   Phần hợp: $Q_{\text{edges}} \cup H_{\text{edges}} = \{(\text{edge-lb}, \text{payment-svc}), (\text{payment-svc}, \text{payment-db}), (\text{payment-svc}, \text{auth-svc})\} \rightarrow |Q \cup H| = 3$
> *   Điểm Jaccard cấu trúc = $\frac{1}{3} \approx 0.333$
>
> **Bước 2: Tính tương đồng số liệu trên cạnh trùng nhau**
> Cạnh trùng nhau duy nhất là $e = (\text{edge-lb}, \text{payment-svc})$.
> *   Tương đồng tỷ lệ lỗi:
>     $$Sim_{\text{error}}(e) = \max(0.0, 1.0 - |0.10 - 0.12|) = 1.0 - 0.02 = 0.98$$
> *   Tương đồng độ lệch trễ:
>     $$Sim_{\text{dev}}(e) = \max\left(0.0, 1.0 - \frac{|3.0 - 2.8|}{3.0 + 2.8}\right) = 1.0 - \frac{0.2}{5.8} \approx 1.0 - 0.034 = 0.966$$
> *   Tương đồng tổng hợp của cạnh $e$:
>     $$Sim_{\text{edge}}(e) = 0.5 \cdot 0.98 + 0.5 \cdot 0.966 = 0.49 + 0.483 = 0.973$$
>
> **Bước 3: Tính điểm tương đồng Trace tổng thể $S_{\text{trace}}$**
> Vì chỉ có 1 cạnh giao nhau, giá trị trung bình trên tập giao là $0.973$.
> $$S_{\text{trace}} = \text{Jaccard cấu trúc} \times \text{Trung bình } Sim_{\text{edge}} = 0.333 \times 0.973 = \mathbf{0.324}$$


#### E. Tương đồng Metric ($S_{\text{metric}}$)
Kết hợp giữa sự trùng khớp của các khóa metric `(service, metric)` bị biến động và tỷ lệ thay đổi (delta ratio) trước/sau thời điểm sự cố.

Gọi $Q_{\text{metrics}}$ là tập khóa metric biến động của live incident, $H_{\text{metrics}}$ là tập khóa metric của lịch sử đã ánh xạ.
Nếu tồn tại các metric giao nhau $Metrics_{\text{intersect}} = Q_{\text{metrics}} \cap H_{\text{metrics}}$:
*   Với mỗi metric $m \in Metrics_{\text{intersect}}$, ta tính tỷ lệ biến đổi tại query ($Ratio_q$) và history ($Ratio_h$):
    $$Ratio_q = \frac{q\_after}{q\_before}, \quad Ratio_h = \frac{h\_after}{h\_before}$$
*   **Tương đồng tỷ lệ thay đổi (Ratio Similarity)**:
    $$Sim_{\text{ratio}}(m) = \max\left(0.0, 1.0 - \frac{|Ratio_q - Ratio_h|}{Ratio_q + Ratio_h}\right)$$

**Điểm tương đồng Metric tổng thể ($S_{\text{metric}}$)**:
$$S_{\text{metric}} = \frac{|Q_{\text{metrics}} \cap H_{\text{metrics}}|}{|Q_{\text{metrics}} \cup H_{\text{metrics}}|} \times \left( \frac{1}{|Metrics_{\text{intersect}}|} \sum_{m \in Metrics_{\text{intersect}}} Sim_{\text{ratio}}(m) \right)$$
*(Nếu không có metric giao nhau nào, $S_{\text{metric}} = 0.0$. Nếu lịch sử không có metric signature, gán $w_{\text{metric}} = 0.0$)*

---

### 1.2. Biện luận Thiết kế: Tại sao công thức tính $S$ của mỗi đặc trưng lại khác nhau?

Mỗi loại dữ liệu giám sát (Observability data) mang đặc tính vật lý và cấu trúc dữ liệu khác nhau. Do đó, việc thiết kế các phép toán tính tương đồng ($S$) phải tương thích với bản chất của từng loại dữ liệu để tránh nhiễu và đạt hiệu quả tối ưu:

#### A. Tại sao Log ($S_{\text{log}}$) chỉ dùng Jaccard cấu trúc?
*   **Bản chất dữ liệu**: Log là dữ liệu dạng phân loại (categorical/textual tokens). Một chữ ký log lỗi (như `"deadlock detected on table"`) chỉ có hai trạng thái: **xuất hiện** hoặc **không xuất hiện**.
*   **Lý do không dùng số liệu**: Hệ thống không quan tâm đến *tần suất* (số lượng dòng log xuất hiện) vì số lượng log phụ thuộc hoàn toàn vào lưu lượng traffic (throughput) tại thời điểm lỗi. Nếu hệ thống đang chịu tải cao, một lỗi có thể sinh ra 10.000 dòng log; nếu tải thấp chỉ sinh ra 10 dòng log, nhưng bản chất lỗi là như nhau. 
*   **Giải pháp**: Sử dụng độ tương đồng tập hợp Jaccard giúp tập trung hoàn toàn vào việc đối sánh live incident có xuất hiện các dấu hiệu lỗi tĩnh tương tự lịch sử hay không, loại bỏ hoàn toàn nhiễu từ traffic.

#### B. Tại sao Trace ($S_{\text{trace}}$) lại kết hợp cả Jaccard và Sai số trị số?
*   **Bản chất dữ liệu**: Trace là dữ liệu đồ thị liên kết (Service Topology Graph) đi kèm thông số hiệu năng động (latency P99, error rate) trên từng cạnh kết nối.
*   **Lý do cần Jaccard cấu trúc**: Để kiểm tra xem luồng lan truyền lỗi (fault propagation path) có giống nhau không. Nếu sự cố A bị lỗi trên đường đi `A -> B -> C`, còn sự cố B bị lỗi trên đường `A -> D -> E`, thì dù chỉ số trễ có giống nhau, nguyên nhân gốc rễ vẫn hoàn toàn khác biệt.
*   **Lý do cần Sai số trị số**: Một cạnh kết nối bị trễ nhẹ (latency tăng gấp 1.2 lần) và bị nghẽn nghiêm trọng (latency tăng gấp 10 lần) đại diện cho hai cấp độ lỗi khác nhau. Việc nhân chỉ số Jaccard với độ lệch trị số ($Sim_{\text{error}}$ và $Sim_{\text{dev}}$) giúp động cơ phân biệt chính xác mức độ nghiêm trọng và hành vi động của lỗi trên luồng truyền tải đó.

#### C. Tại sao Metric ($S_{\text{metric}}$) lại tính theo Tỷ lệ thay đổi (Delta Ratio) thay vì hiệu số tuyệt đối?
*   **Bản chất dữ liệu**: Metric là các chuỗi thời gian số học liên tục đo lường tài nguyên phần cứng (CPU, Memory, Connection Pool).
*   **Lý do không dùng hiệu số tuyệt đối**: Giả sử sự cố lịch sử ghi nhận CPU tăng từ $10\% \rightarrow 80\%$ (tăng tuyệt đối $70\%$). Live incident ghi nhận CPU tăng từ $2\% \rightarrow 16\%$ (tăng tuyệt đối $14\%$). Nếu tính hiệu số tuyệt đối, hai biến động này bị coi là rất khác nhau.
*   **Giải pháp**: Tính theo tỷ lệ thay đổi (Delta Ratio):
    $$\text{Ratio} = \frac{\text{Giá trị trong sự cố (after)}}{\text{Giá trị bình thường (before)}}$$
    Cả hai trường hợp trên đều có $\text{Ratio} = 8.0$ (CPU đều tăng vọt gấp 8 lần). Việc tính toán dựa trên Ratio giúp thuật toán **bỏ qua tải nền (baseline load scale)** tại thời điểm xảy ra sự cố và chỉ tập trung vào **mức độ đột biến** của tài nguyên, giúp nhận diện chính xác bản chất hành vi lỗi bất kể tải hệ thống lớn hay nhỏ.



---

### 1.3. Bỏ phiếu trọng số kết quả (Outcome-Weighted Voting)
Trọng số phiếu bầu $Vote(a)$ của một sự cố lịch sử dành cho hành động $a$ tỷ lệ thuận với điểm tương đồng và kết quả thực tế của sự cố đó:

$$Vote(a) = Sim(q, h) \times OutcomeWeight(h)$$

Trong đó:
*   $OutcomeWeight = +1.0$ nếu kết quả là `success` (Thành công).
*   $OutcomeWeight = +0.5$ nếu kết quả là `partial` (Thành công một phần).
*   $OutcomeWeight = -1.0$ nếu kết quả là `failed` (Thất bại - phạt phiếu âm).

---

## 2. Công thức Layer 3: Risk-Sensitive Decision Making

### 2.1. Xác suất thành công hiệu chỉnh ($P_{\text{success}}$)
Để tránh các hành động có ít phiếu bầu thắng thế, xác suất thành công của hành động $a$ được hiệu chỉnh theo tỷ lệ điểm đồng thuận (`consensus_score`):

$$P_{\text{success}}(a) = \max\left(0.01, \min\left(0.95, Sim_{\text{max}} \times \frac{Score(a)}{Score_{\text{max}}}\right)\right)$$

*Đối với phương án dự phòng gọi kỹ sư trực ca (`page_oncall`), xác suất thành công mặc định là $0.99$.*

---

### 2.2. Điểm phạt chi phí (Action Penalty)
Mỗi hành động trong catalog mang một mức phạt chi phí dựa trên thời gian và phạm vi ảnh hưởng:

$$Penalty(a) = \text{cost\_min} + 2 \cdot \text{downtime\_min} + 5 \cdot \text{blast\_radius\_services} + VirtualPenalty$$

*Trong đó, VirtualPenalty = 70.0 chỉ áp dụng cho `page_oncall` để làm phương án cuối cùng.*

---

### 2.3. Giá trị kỳ vọng (Expected Value - EV)
Động cơ áp dụng công thức EV để tìm hành động có lợi ích ròng cao nhất:

$$EV(a) = P_{\text{success}}(a) \cdot (100 - Penalty(a)) + (1 - P_{\text{success}}(a)) \cdot (-150 - Penalty(a))$$

*   **100**: Lợi ích ròng khi khắc phục lỗi thành công.
*   **-150**: Tổn thất khi hành động thất bại (phải gánh thêm thiệt hại hệ thống).

---

## 3. Ví dụ Tính toán thực tế (Sự cố E03 - Memory Leak)

Dưới đây là từng bước tính toán EV của sự cố **E03** trên dịch vụ `esb`.

### Bước 1: Tính xác suất thành công hiệu chỉnh ($P_{\text{success}}$)
*   Độ tương đồng lớn nhất: $Sim_{\text{max}} = 0.809$
*   Điểm đồng thuận cao nhất: $Score_{\text{max}} = 1.283$ (dành cho `rollback_service`, sau khi loại bỏ action trùng trong cùng một incident lịch sử)
*   Điểm đồng thuận của `increase_pool_size`: $Score = 0.474$

Tính toán:
1.  **Hành động `rollback_service`**:
    $$P_{\text{success}} = 0.809 \times \frac{1.283}{1.283} = 0.809 \approx \mathbf{0.81}$$
2.  **Hành động `increase_pool_size`**:
    $$P_{\text{success}} = 0.809 \times \frac{0.474}{1.283} = 0.299 \approx \mathbf{0.30}$$
3.  **Hành động `page_oncall`**:
    $$P_{\text{success}} = \mathbf{0.99}$$

---

### Bước 2: Tính toán Hình phạt Chi phí (Penalty)
Dựa trên cấu hình trong `actions.yaml`:
1.  **`rollback_service`** (cost=10, downtime=2, blast=1):
    $$Penalty = 10 + 2 \cdot 2 + 5 \cdot 1 = \mathbf{19.0}$$
2.  **`increase_pool_size`** (cost=1, downtime=0, blast=1):
    $$Penalty = 1 + 2 \cdot 0 + 5 \cdot 1 = \mathbf{6.0}$$
3.  **`page_oncall`** (cost=0, downtime=0, blast=0, virtual=70):
    $$Penalty = 0 + 2 \cdot 0 + 5 \cdot 0 + 70.0 = \mathbf{70.0}$$

---

### Bước 3: Tính Giá trị Kỳ vọng (EV)
Áp dụng công thức EV:

1.  **Hành động `rollback_service`**:
    $$EV = 0.81 \cdot (100 - 19) + 0.19 \cdot (-150 - 19)$$
    $$EV = 0.81 \cdot 81 + 0.19 \cdot (-169)$$
    $$EV = 65.53 - 32.28 = \mathbf{33.25}$$

2.  **Hành động `increase_pool_size`**:
    $$EV = 0.30 \cdot (100 - 6) + 0.70 \cdot (-150 - 6)$$
    $$EV = 0.30 \cdot 94 + 0.70 \cdot (-156)$$
    $$EV = 28.12 - 109.40 = \mathbf{-81.28}$$

3.  **Hành động `page_oncall`**:
    $$EV = 0.99 \cdot (100 - 70) + 0.01 \cdot (-150 - 70)$$
    $$EV = 0.99 \cdot 30 + 0.01 \cdot (-220)$$
    $$EV = 29.70 - 2.20 = \mathbf{27.50}$$

### Kết quả quyết định:
Hành động **`rollback_service`** thắng cuộc vì có điểm EV lớn nhất ($33.25 > 27.50 > -81.28$). Động cơ tự động rollback dịch vụ `esb` thay vì gọi kỹ sư trực ca.
