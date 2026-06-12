# W2-D3 Submit

## Run

From the D3 folder:

```powershell
cd D:\Xbrain\aiops-nguyenphananhbao\w2\d3
$env:AIOPS_USE_LLM="false"
uvicorn serve:app --port 8000 --workers 1
```

The service resolves paths from `serve.py` using `Path(__file__)`, so it does not depend on the current working directory when loading D1/D2 data.

## Smoke Tests

```powershell
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
curl -X POST http://127.0.0.1:8000/incident -H "Content-Type: application/json" -d "{}"
curl -X POST http://127.0.0.1:8000/incident -H "Content-Type: application/json" -d "{\"alerts\":\"bad\"}"
```

Expected behavior:

- `/healthz` returns `{"status":"ok"}`.
- `/readyz` returns `{"status":"ready", ...}` when D1/D2 files exist.
- Valid `/incident` input returns HTTP 200 with `clusters`, `root_cause`, `recommended_actions`, and `rca`.
- Invalid input such as `{"alerts":"bad"}` returns HTTP 422 instead of 500.

## Reflection

I used FastAPI because the lab needs a small API wrapper with reliable validation. Pydantic handles invalid JSON shapes and timestamp normalization for both `ts` and `timestamp`. The pipeline uses graph + retrieval only, so `AIOPS_USE_LLM=false` is safe for concurrency benchmarks and there is no external API dependency.

The service is designed for `--workers 1` on a weak machine. Static graph/history/sample data are cached in memory, and each request only performs lightweight session grouping, graph traversal, and top-k incident retrieval. The expected sample result has 3 clusters, with the main root cause as `payment-svc`, class `connection_pool_exhaustion`, and recommended actions from payment incident history.
