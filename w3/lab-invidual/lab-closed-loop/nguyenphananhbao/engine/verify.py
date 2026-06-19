"""Prometheus-based verify step for the closed-loop orchestrator."""

import time
import requests

from engine.logger import JsonLogger

log = JsonLogger("verify")


def normalize_service(service: str) -> str:
    """Normalize service name by stripping 'ronki-' prefix if present."""
    if service.startswith("ronki-"):
        return service[len("ronki-"):]
    return service


def query_prometheus(prometheus_url: str, promql: str) -> float | None:
    """Instant query; return scalar value or None on error."""
    try:
        resp = requests.get(
            f"{prometheus_url}/api/v1/query",
            params={"query": promql},
            timeout=5,
        )
        resp.raise_for_status()
        results = resp.json().get("data", {}).get("result", [])
        if results and len(results) > 0:
            # Value is represented as a list: [timestamp, "string_value"]
            val_str = results[0]["value"][1]
            return float(val_str)
    except Exception as exc:
        log.error("PROMETHEUS_QUERY_ERROR", query=promql, error=str(exc))
    return None


def verify_service(
    prometheus_url: str,
    service: str,
    baseline: dict,
    timeout_s: int,
    poll_interval_s: int,
    min_samples: int,
) -> bool:
    """Poll Prometheus until metrics are within threshold or timeout expires.

    Returns True on pass (min_samples consecutive healthy reads), False on timeout.
    """
    normalized_svc = normalize_service(service)
    thresholds = baseline["verify_thresholds"]
    queries = baseline["prometheus_queries"]

    # Replace placeholder with normalized service name
    latency_q = queries["latency_p99"].replace("{service}", normalized_svc)
    up_q = queries["up"].replace("{service}", normalized_svc)

    # Cast baseline thresholds explicitly to float
    latency_max = float(thresholds["latency_p99_max_ms"])
    up_req = float(thresholds["up_required"])

    deadline = time.time() + timeout_s
    passes = 0
    samples = 0

    log.info("VERIFY_START", service=service, normalized_service=normalized_svc, timeout_s=timeout_s)

    while time.time() < deadline:
        latency = query_prometheus(prometheus_url, latency_q)
        up = query_prometheus(prometheus_url, up_q)
        samples += 1

        latency_ok = False
        if latency is not None:
            # Explicit float comparison
            latency_ok = float(latency) < latency_max

        up_ok = False
        if up is not None:
            # Explicit float comparison
            up_ok = float(up) >= up_req

        log.info(
            "VERIFY_SAMPLE",
            service=service,
            normalized_service=normalized_svc,
            sample=samples,
            latency_p99_ms=latency,
            up=up,
            latency_ok=latency_ok,
            up_ok=up_ok,
        )

        if latency_ok and up_ok:
            passes += 1
            if passes >= min_samples:
                log.info("VERIFY_PASS", service=service, samples=samples)
                return True
        else:
            passes = 0  # require consecutive passes

        time.sleep(poll_interval_s)

    log.warning("VERIFY_FAIL", service=service, samples=samples)
    return False
