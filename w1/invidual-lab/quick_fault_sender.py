#!/usr/bin/env python3
"""Send a quick synthetic fault to the local pipeline for manual testing."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from urllib import request


FAULT_PAYLOADS = {
    "memory_leak": {
        "memory_usage_bytes": 1_760_000_000,
        "memory_limit_bytes": 2_000_000_000,
        "cpu_usage_percent": 82.0,
        "http_requests_per_sec": 130.0,
        "http_p99_latency_ms": 520.0,
        "http_5xx_rate": 8.0,
        "jvm_gc_pause_ms_avg": 140.0,
        "queue_depth": 8,
        "upstream_timeout_rate": 0.1,
    },
    "traffic_spike": {
        "memory_usage_bytes": 820_000_000,
        "memory_limit_bytes": 2_000_000_000,
        "cpu_usage_percent": 88.0,
        "http_requests_per_sec": 920.0,
        "http_p99_latency_ms": 1_100.0,
        "http_5xx_rate": 12.0,
        "jvm_gc_pause_ms_avg": 14.0,
        "queue_depth": 170,
        "upstream_timeout_rate": 0.2,
    },
    "dependency_timeout": {
        "memory_usage_bytes": 830_000_000,
        "memory_limit_bytes": 2_000_000_000,
        "cpu_usage_percent": 58.0,
        "http_requests_per_sec": 280.0,
        "http_p99_latency_ms": 1_900.0,
        "http_5xx_rate": 22.0,
        "jvm_gc_pause_ms_avg": 15.0,
        "queue_depth": 95,
        "upstream_timeout_rate": 44.0,
    },
}

FAULT_LOGS = {
    "memory_leak": "OutOfMemoryWarning: heap usage at 88%",
    "traffic_spike": "Request rejected: server overloaded",
    "dependency_timeout": "Circuit breaker OPEN for payment-service",
}


def send_payload(target: str, fault_type: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    payload = {
        "timestamp": timestamp,
        "metrics": FAULT_PAYLOADS[fault_type],
        "logs": [
            {
                "timestamp": timestamp,
                "level": "ERROR",
                "service": "cart-service",
                "pod": "cart-service-test",
                "message": FAULT_LOGS[fault_type],
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        target,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=2) as response:
        print(response.status, response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Send synthetic anomaly payloads")
    parser.add_argument(
        "--type",
        choices=sorted(FAULT_PAYLOADS),
        default="dependency_timeout",
        help="Fault type to send",
    )
    parser.add_argument("--target", default="http://localhost:8000/ingest")
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    for index in range(args.count):
        send_payload(args.target, args.type)
        if index + 1 < args.count:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
