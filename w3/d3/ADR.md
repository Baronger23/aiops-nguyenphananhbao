# ADR-001: Implementing Multi-Variate Ensemble Anomaly Detection for CPU-Bound and Scraper-Timeout Failures

## Status
accepted

## Context
During the reproduction and analysis of the **Cloudflare WAF Regex (2019-07-02)** outage, the current AIOps pipeline was observed to have a major monitoring blindspot. The pipeline only monitors application-level metrics (`up`, `http_request_duration_seconds`, and `http_requests_total`). 

When catastrophic backtracking occurred, the CPU utilization spiked to 100% and the application container hung. This led to two critical failures in the detection pipeline (as documented in [postmortem.md](file:///d:/Xbrain/aiops-nguyenphananhbao/w3/d3/postmortem.md)):
1. **CPU Blindness:** The pipeline lacks integration with host or container CPU resource metrics, failing to recognize 100% CPU saturation.
2. **Scrape Timeout:** When the target container is fully pinned, Prometheus scrapers timeout, meaning the pipeline receives no metrics (or returns empty values) and fails to raise any latency or error alerts.

We need to redesign our detection layer to capture resource-exhaustion incidents and handle missing metric conditions.

## Decision
We will implement a multi-variate ensemble anomaly detector that integrates container/host system metrics (CPU, Memory, and Thread count) alongside application metrics, and treats metric scraping timeouts (missing data) as high-priority anomalies rather than ignoring them.

## Alternatives Considered

1. **Static Threshold Alerting on CPU Usage**
   * *Pros:* Simple to implement using standard Prometheus rules (e.g., `container_cpu_usage_seconds_total > 90%`). Extremely low CPU/memory overhead for the pipeline itself.
   * *Cons:* Prone to high rates of false positives during scheduled background jobs or peak traffic hours. It also fails to solve the scraper timeout issue—if the scraper times out, Prometheus cannot query the CPU metric, and the alert will still not trigger.

2. **Ensemble Anomaly Detection (3σ + Isolation Forest + Dead-Man's Switch for Scraper)**
   * *Pros:* Detects multivariate anomalies (e.g., CPU spikes correlating with low request throughput). The inclusion of a "Dead-Man's Switch" (which alerts if a container fails to be scraped for 2 consecutive cycles) directly solves the scraper-timeout issue. Highly adaptable to traffic patterns without hardcoded static thresholds.
   * *Cons:* Higher complexity to implement, train, and maintain. Requires historical baselines and introduces computational overhead in the AIOps pipeline runtime.

3. **Application-Level Middleware Instrumentation Only**
   * *Pros:* Keeps the logic inside the app codebase. Can capture regex execution time directly within the WAF middleware.
   * *Cons:* Requires modifying all service codebases (invasive). If the Python event loop is blocked by a synchronous CPU-bound task (like python regex execution), application middleware cannot run to report metrics, rendering it useless.

## Consequences
- **Positive (Positive Consequence):** The pipeline gains robust detection capabilities for silent, CPU-pinned outages (such as catastrophic backtracking, infinite loops, and resource leaks). The Dead-Man's Switch successfully flags scraper-timeout situations, eliminating the blindspot observed in the Cloudflare regex reproduction.
- **Negative (Trade-off):** Higher engineering maintenance effort and computational overhead in the pipeline. Managing false positives from the Isolation Forest model during sudden scaling events requires careful validation.
- **Risks Introduced:** Model drift may cause the anomaly detector to become less sensitive over time if the baseline window is not retrained regularly.
- **What gets locked in:** The schema of the input metrics fetched from Prometheus must now consistently include container resource metrics (`container_cpu_usage_seconds_total`, etc.) and scrape state metrics (`up`).
