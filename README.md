# AIOps Nguyen Phan Anh Bao

Repo này là tập hợp các bài tập trong quá trình học tập AIOps. Nội dung được tổ chức theo từng tuần và từng ngày, đi từ các bài cơ bản như phát hiện bất thường trên time-series/log cho tới các pipeline nâng cao hơn như alert correlation, RCA và service API.

## Mục tiêu học tập

Các bài trong repo tập trung vào những năng lực cốt lõi của AIOps:

- Phát hiện bất thường trên dữ liệu metric/time-series.
- Phân tích log và gom nhóm template log.
- Thiết kế pipeline xử lý sự cố.
- Gom alert thành cluster để giảm noise.
- Tìm root cause bằng service graph và incident history.
- Đóng gói pipeline RCA thành API có thể gọi bằng HTTP.

## Cấu trúc repo

```text
w1/
  day-1/          Bài phát hiện anomaly trên time-series
  day-2/          Bài phân tích log HDFS và template spike
  day-3/          Bài thiết kế architecture, pipeline và cost model
  invidual-lab/   Bài lab cá nhân về stream alert/pipeline

w2/
  d1/             Alert Correlator: dedup, session window, topology grouping
  d2/             RCA pipeline: graph scoring, retrieval, suggested actions
  d3/             FastAPI service cho pipeline correlation + RCA
  nguyenphananhbao/
                  Evidence-driven remediation engine
```

## Một số kết quả chính

### W2-D1: Alert Correlator

Pipeline trong `w2/d1` biến alert flood thành ít cluster hơn:

```text
20 alerts -> 3 clusters
reduction_ratio = 0.85
```

Các bước chính:

```text
dedup fingerprint
-> session window gap_sec=120
-> topology grouping max_hop=2
-> results/cluster_summary.json
```

### W2-D2: RCA Pipeline

Pipeline trong `w2/d2` dùng service graph và incident history để tìm root cause:

```text
main root cause = payment-svc
class = connection_pool_exhaustion
method = graph+retrieval
```

Output chính nằm ở:

```text
w2/d2/results/rca_output.json
```

### W2-D3: FastAPI RCA Service

`w2/d3/serve.py` đóng gói pipeline correlation + RCA thành API.

Chạy service:

```powershell
cd w2\d3
$env:AIOPS_USE_LLM="false"
uvicorn serve:app --port 8000 --workers 1
```

Kiểm tra nhanh:

```powershell
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
curl -X POST http://127.0.0.1:8000/incident -H "Content-Type: application/json" -d "{}"
```

Response `/incident` có các trường chính:

```json
{
  "clusters": [],
  "root_cause": "payment-svc",
  "recommended_actions": [],
  "rca": []
}
```

## Công nghệ sử dụng

- Python
- Jupyter Notebook
- FastAPI / Uvicorn
- Pydantic
- Service graph / graph traversal
- Retrieval-based RCA
- JSON / JSONL / CSV

Một số bài có thể chạy chỉ với Python standard library. Riêng API ở `w2/d3` cần cài thêm:

```powershell
pip install fastapi uvicorn pydantic networkx cachetools prometheus-client
```

## Ghi chú

Repo này phục vụ mục đích học tập, thực hành và nộp bài trong quá trình học AIOps. Các dataset và incident history trong repo là dữ liệu mẫu/synthetic để mô phỏng hệ thống microservice e-commerce.