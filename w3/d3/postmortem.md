# Postmortem: Cloudflare WAF Regex Catastrophic Backtracking (2019-07-02)

## Summary
On July 2, 2019, the deployment of a new Web Application Firewall (WAF) rule containing an unoptimized regular expression triggered global CPU exhaustion across all edge nodes. The catastrophic backtracking occurred on every incoming HTTP request, rendering the global proxy network unresponsive. The service was recovered after 27 minutes of total downtime by performing a manual rollback of the faulty WAF rule configuration.

## Impact
- **Users affected:** ~100% of global Cloudflare traffic (including DNS and proxy service).
- **Services affected:** WAF, CDN Proxy, and DNS resolution.
- **Revenue/SLA impact:** Severe SLA breach; significant traffic loss for millions of websites.
- **Duration:** 13:42:00 UTC → 14:09:00 UTC, total duration of 27 minutes.

## Timeline (UTC)

| UTC | Event |
|-----|-------|
| 2019-07-02 13:42:00 | The automated global deployment pipeline completed the rollout of a new WAF rule to all edge nodes without a canary validation stage. |
| 2019-07-02 13:42:15 | The first HTTP request containing an adversarial pattern was received, triggering the nested quantifier regex execution path in the WAF middleware. |
| 2019-07-02 13:42:30 | Core CPU #1 on edge servers reached 100% utilization due to catastrophic regex backtracking. |
| 2019-07-02 13:43:00 | Edge proxy gateways logged a significant increase in HTTP Request Queue depth as processing threads hung. |
| 2019-07-02 13:43:30 | External synthetic monitors and public clients registered HTTP Connection Timeout errors (504 Gateway Timeout). |
| 2019-07-02 13:44:00 | Internal validation probes sending clean HTTP requests to the edge servers were completely blocked, confirming a total service lockout. |
| 2019-07-02 13:45:00 | The automated paging system triggered an on-call alert for high global CPU utilization, though the underlying cause remained unidentified. |
| 2019-07-02 14:09:00 | The automated deployment pipeline executed a configuration rollback to the previous stable WAF ruleset, restoring CPU and traffic flow to normal. |

## Root cause
The root cause was the deployment of an unoptimized regular expression containing nested quantifiers `(?:(?:"|\d|.*)+(?:.*=.*))` on a hot execution path, which caused the regex engine to perform exponential backtracking when processing specific query parameters.

## Contributing factors
1. **Lack of Canary Rollouts:** The WAF deployment system lacked a phased canary or blue-green deployment stage, which allowed the faulty regex rule to be applied globally to all edge nodes simultaneously.
2. **Missing Static Analysis in CI:** The staging validation pipeline did not include a static analysis tool capable of detecting potentially dangerous regular expressions (e.g., regex engines prone to catastrophic backtracking) before deployment.
3. **Absence of Regex Execution Timeouts:** The WAF runtime environment lacked a strict timeout threshold for regex evaluations, allowing a single matching attempt to consume CPU cycles indefinitely.

## Detection
- **How was it detected?** The incident was detected via an automated paging alert for high CPU utilization on edge proxy nodes, followed by external user reports of service unresponsiveness.
- **MTTD:** 3 minutes (from the deployment at 13:42:00 UTC to the Prometheus CPU alert at 13:45:00 UTC).
- **Pipeline gaps observed during reproduction:**
  - **Gap 1: Missing System-Level CPU Scrapes:** The AIOps pipeline was entirely blind to the incident because it only monitored application-level availability (`up`) and HTTP request counts. It lacked integration with Prometheus system CPU metrics (`node_cpu_seconds_total`), leaving the CPU pegging completely undetected.
  - **Gap 2: Edge-Case Latency Timeout Handling:** The pipeline's latency detector timed out and returned empty results because the simulated API container hung completely and failed to respond to the Prometheus scraper, causing the pipeline to miss the latency metric updates.

## Response
- **First responder action:** The on-call engineering team declared a Sev-1 incident, verified that the CPU exhaustion coincided with a recent WAF configuration update, and prepared a configuration rollback command.
- **Time to mitigate:** 27 minutes (rollback completed at 14:09:00 UTC).
- **Time to fully resolve:** 27 minutes.

## Action items

| # | Action | Owner | Type | ETA |
|---|--------|-------|------|-----|
| 1 | Implement static regex analysis (e.g., using `safe-regex`) in the CI pipeline to block rules containing catastrophic backtracking patterns. | CI/CD Engineer | preventive | 2026-06-30 |
| 2 | Add a maximum execution timeout (e.g., 50ms) to the regex matching middleware in the WAF engine. | WAF Platform Team | preventive | 2026-07-15 |
| 3 | Integrate CPU and thread utilization monitoring into the AIOps pipeline alert suite to trigger early anomaly alarms. | AIOps Platform Engineer | detective | 2026-06-25 |
| 4 | Restructure the deployment pipeline to roll out WAF rules in staged waves (canaries) instead of a single global deploy. | Release Engineer | mitigation | 2026-07-20 |
