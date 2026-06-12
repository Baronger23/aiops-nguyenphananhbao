import json
from datetime import datetime

def parse_metric_delta(s: str) -> tuple[float, float]:
    parts = s.replace("->", "|").split("|")
    if len(parts) != 2:
        raise ValueError(f"unexpected delta format: {s!r}")
    return float(parts[0].strip()), float(parts[1].strip())

def map_log_message_to_signature(msg: str) -> str | None:
    msg_lower = msg.lower()
    
    # 429 returned to upstream
    if "429 returned" in msg_lower or "429" in msg_lower:
        if "429 returned to upstream" in msg_lower or "429 too many requests" in msg_lower:
            return "429 returned to upstream"
            
    # ConnectionPool: timeout acquiring connection
    if "connectionpool: timeout acquiring connection" in msg_lower or "timeout acquiring connection" in msg_lower:
        return "ConnectionPool: timeout acquiring connection"
        
    # DB query latency / query took longer
    if "db query latency" in msg_lower or "query latency >" in msg_lower or "query took" in msg_lower:
        if "latency > 5s" in msg_lower or "longer than threshold" in msg_lower:
            if "query took longer" in msg_lower:
                return "query took longer than threshold"
            return "DB query latency > 5s on table"
            
    # Failed to forward request: pool exhausted
    if "pool exhausted" in msg_lower or ("failed to forward request" in msg_lower and "exhausted" in msg_lower):
        return "Failed to forward request: pool exhausted"
        
    # GC pause: 4127ms (full GC, heap
    if "gc pause" in msg_lower:
        return "GC pause: 4127ms (full GC, heap"
        
    # OutOfMemoryError: Java heap space
    if "outofmemoryerror" in msg_lower or "java heap space" in msg_lower:
        return "OutOfMemoryError: Java heap space"
        
    # Pod evicted: node out of memory
    if "pod evicted" in msg_lower or "node out of memory" in msg_lower:
        return "Pod evicted: node out of memory"
        
    # Retry exhausted after 5 attempts
    if "retry exhausted" in msg_lower or ("retry" in msg_lower and "exhausted" in msg_lower):
        return "Retry exhausted after 5 attempts"
        
    # TLS handshake failed: certificate has expired
    if "certificate has expired" in msg_lower or ("handshake failed" in msg_lower and "expired" in msg_lower):
        return "TLS handshake failed: certificate has expired"
        
    # cgroup OOM kill
    if "cgroup oom kill" in msg_lower or "oom kill" in msg_lower:
        return "cgroup OOM kill"
        
    # consumer rebalance triggered
    if "consumer rebalance" in msg_lower:
        return "consumer rebalance triggered"
        
    # deadlock detected on table
    if "deadlock detected" in msg_lower:
        return "deadlock detected on table"
        
    # degraded behavior detected
    if "degraded behavior" in msg_lower:
        return "degraded behavior detected"
        
    # fallback failed, retrying request
    if "fallback failed" in msg_lower and "retrying" in msg_lower:
        return "fallback failed, retrying request"
        
    # feature distribution drift detected on field
    if "feature distribution drift" in msg_lower or "drift detected on field" in msg_lower:
        return "feature distribution drift detected on field"
        
    # lock timeout exceeded after
    if "lock timeout" in msg_lower:
        return "lock timeout exceeded after"
        
    # model inference confidence dropped below threshold
    if "model inference confidence" in msg_lower or "inference confidence" in msg_lower:
        return "model inference confidence dropped below threshold"
        
    # partition reassignment in progress
    if "partition reassignment" in msg_lower:
        return "partition reassignment in progress"
        
    # rate limit exceeded for client
    if "rate limit exceeded" in msg_lower:
        return "rate limit exceeded for client"
        
    # service error rate elevated
    if "service error rate" in msg_lower or "error rate elevated" in msg_lower:
        return "service error rate elevated"
        
    # x509: certificate signed by unknown authority
    if "x509: certificate" in msg_lower or "unknown authority" in msg_lower:
        return "x509: certificate signed by unknown authority"
        
    return None

def extract_trace_anomalies(traces: list[dict], detected_at_str: str) -> list[dict]:
    # Group trace records by (from, to)
    groups = {}
    for t in traces:
        key = (t["from"], t["to"])
        if key not in groups:
            groups[key] = []
        groups[key].append(t)
        
    anomalies = []
    for (f_svc, t_svc), records in groups.items():
        # Baseline traces are before detected_at, incident traces are after
        baseline_records = [r for r in records if r["ts"] < detected_at_str]
        incident_records = [r for r in records if r["ts"] >= detected_at_str]
        
        # Calculate baseline metrics
        base_count = sum(r["count"] for r in baseline_records)
        if base_count > 0:
            base_p99 = sum(r["p99_ms"] * r["count"] for r in baseline_records) / base_count
        else:
            # Fallback to average p99 of baseline directly
            base_p99 = sum(r["p99_ms"] for r in baseline_records) / max(1, len(baseline_records))
            
        if base_p99 <= 0:
            base_p99 = 100.0  # Safe default baseline latency
            
        # Calculate incident metrics
        inc_count = sum(r["count"] for r in incident_records)
        inc_errors = sum(r["error_count"] for r in incident_records)
        if inc_count > 0:
            inc_p99 = sum(r["p99_ms"] * r["count"] for r in incident_records) / inc_count
            error_rate = inc_errors / inc_count
        else:
            inc_p99 = sum(r["p99_ms"] for r in incident_records) / max(1, len(incident_records))
            error_rate = 0.0
            
        p99_deviation_ratio = inc_p99 / base_p99
        
        # We classify as anomalous if there's any deviation or error rate
        if error_rate > 0.01 or p99_deviation_ratio > 1.2:
            anomalies.append({
                "from": f_svc,
                "to": t_svc,
                "p99_deviation_ratio": round(p99_deviation_ratio, 2),
                "error_rate": round(error_rate, 4)
            })
            
    return anomalies

def extract_metric_deltas(metrics_window: dict, detected_at_str: str) -> list[dict]:
    samples = metrics_window.get("samples", {})
    deltas = []
    
    for full_name, ts_values in samples.items():
        # Split full name by first dot to get service and metric
        parts = full_name.split(".", 1)
        if len(parts) == 2:
            service, metric = parts
        else:
            service, metric = full_name, ""
            
        baseline_vals = [val for ts, val in ts_values if ts < detected_at_str]
        incident_vals = [val for ts, val in ts_values if ts >= detected_at_str]
        
        avg_base = sum(baseline_vals) / max(1, len(baseline_vals))
        avg_inc = sum(incident_vals) / max(1, len(incident_vals))
        
        # Check if metric has significant change
        abs_diff = abs(avg_inc - avg_base)
        ratio = avg_inc / max(1e-5, avg_base)
        
        # Only report if significant change
        if abs_diff > 1.0 or ratio > 1.2 or ratio < 0.8:
            deltas.append({
                "service": service,
                "metric": metric,
                "delta": f"{round(avg_base, 3)} -> {round(avg_inc, 3)}"
            })
            
    return deltas

def derive_affected_services(trigger_alert: dict, trace_anomalies: list[dict], logs: list[dict], detected_at_str: str) -> list[str]:
    affected = set()
    
    # 1. Alert service
    affected.add(trigger_alert["service"])
    
    # 2. Trace anomaly services (both sender and receiver)
    for t in trace_anomalies:
        if t["error_rate"] > 0.05 or t["p99_deviation_ratio"] > 1.5:
            affected.add(t["from"])
            affected.add(t["to"])
            
    # 3. Log error burst services (>= 5 error/warn logs in incident window)
    log_counts = {}
    for l in logs:
        if l["ts"] >= detected_at_str and l["level"] in ("ERROR", "WARN", "FATAL"):
            svc = l["svc"]
            log_counts[svc] = log_counts.get(svc, 0) + 1
            
    for svc, count in log_counts.items():
        if count >= 5:
            affected.add(svc)
            
    # Sort for deterministic output
    return sorted(list(affected))

def extract_features(incident: dict) -> dict:
    detected_at = incident["detected_at"]
    
    # Parse logs to templates
    matched_sigs = set()
    for log in incident.get("logs", []):
        sig = map_log_message_to_signature(log.get("msg", ""))
        if sig:
            matched_sigs.add(sig)
            
    # Extract trace anomalies
    trace_anoms = extract_trace_anomalies(incident.get("traces", []), detected_at)
    
    # Extract metric deltas
    metric_anoms = extract_metric_deltas(incident.get("metrics_window", {}), detected_at)
    
    # Derive affected services
    affected_services = derive_affected_services(
        incident["trigger_alert"],
        trace_anoms,
        incident.get("logs", []),
        detected_at
    )
    
    return {
        "incident_id": incident["incident_id"],
        "trigger_alert": incident["trigger_alert"],
        "affected_services": affected_services,
        "log_signatures": sorted(list(matched_sigs)),
        "trace_signatures": trace_anoms,
        "metric_signatures": metric_anoms
    }
