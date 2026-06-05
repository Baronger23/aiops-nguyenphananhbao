#!/usr/bin/env python3
"""Streaming anomaly detector for AIOps W1 individual lab.

Run:
    python pipeline.py

Endpoint:
    POST http://localhost:8000/ingest
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ALERTS_FILE = Path(__file__).with_name("alerts.jsonl")
WINDOW_SIZE = 12
CONSECUTIVE_HITS = 2
EWMA_ALPHA = 0.25

BASELINES = {
    "memory_pct": {"normal_high": 0.42, "soft_high": 0.65, "hard_high": 0.80},
    "cpu_usage_percent": {"normal_high": 45.0, "soft_high": 65.0, "hard_high": 85.0},
    "http_requests_per_sec": {"normal_high": 160.0, "soft_high": 250.0, "hard_high": 650.0},
    "http_p99_latency_ms": {"normal_high": 65.0, "soft_high": 250.0, "hard_high": 900.0},
    "http_5xx_rate": {"normal_high": 0.8, "soft_high": 3.0, "hard_high": 12.0},
    "jvm_gc_pause_ms_avg": {"normal_high": 18.0, "soft_high": 45.0, "hard_high": 120.0},
    "queue_depth": {"normal_high": 10.0, "soft_high": 35.0, "hard_high": 120.0},
    "upstream_timeout_rate": {"normal_high": 0.4, "soft_high": 4.0, "hard_high": 30.0},
}


class DetectorState:
    def __init__(self) -> None:
        self.window: deque[dict[str, Any]] = deque(maxlen=WINDOW_SIZE)
        self.ewma: dict[str, float] = {}
        self.ewma_deviation: dict[str, float] = {}
        self.hit_counts = {
            "memory_leak": 0,
            "traffic_spike": 0,
            "dependency_timeout": 0,
        }
        self.alerted_types: set[str] = set()
        self.received = 0


STATE = DetectorState()


def analyze_logs(logs: list[dict[str, Any]]) -> dict[str, Any]:
    result = {
        "error_signal": False,
        "warning_signal": False,
        "memory_keywords": False,
        "traffic_keywords": False,
        "dependency_keywords": False,
        "matched_messages": [],
    }

    keyword_map = {
        "memory_keywords": ["outofmemory", "out of memory", "oom", "heap", "gc pause", "gc overhead"],
        "traffic_keywords": ["queue depth high", "overloaded", "rejected", "server overloaded"],
        "dependency_keywords": ["upstream timeout", "circuit breaker", "connection refused", "connection reset", "unavailable", "503", "gateway"],
    }

    for log in logs:
        level = str(log.get("level", "")).upper()
        message = str(log.get("message", ""))
        message_lower = message.lower()

        if level in {"ERROR", "FATAL"}:
            result["error_signal"] = True
            result["matched_messages"].append(message)
        if level == "WARN":
            result["warning_signal"] = True

        for signal, keywords in keyword_map.items():
            if any(keyword in message_lower for keyword in keywords):
                result[signal] = True
                result["matched_messages"].append(message)

    return result


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return variance ** 0.5


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _metric_values(recent: list[dict[str, Any]], field: str) -> list[float]:
    return [float(item["signals"].get(field, 0)) for item in recent]


def _extract_metric_signals(metrics: dict[str, Any]) -> dict[str, float]:
    memory_usage = float(metrics.get("memory_usage_bytes", 0))
    memory_limit = max(float(metrics.get("memory_limit_bytes", 1)), 1)
    return {
        "memory_pct": memory_usage / memory_limit,
        "cpu_usage_percent": float(metrics.get("cpu_usage_percent", 0)),
        "http_requests_per_sec": float(metrics.get("http_requests_per_sec", 0)),
        "http_p99_latency_ms": float(metrics.get("http_p99_latency_ms", 0)),
        "http_5xx_rate": float(metrics.get("http_5xx_rate", 0)),
        "jvm_gc_pause_ms_avg": float(metrics.get("jvm_gc_pause_ms_avg", 0)),
        "queue_depth": float(metrics.get("queue_depth", 0)),
        "upstream_timeout_rate": float(metrics.get("upstream_timeout_rate", 0)),
    }


def _update_ewma(signals: dict[str, float]) -> None:
    for field, value in signals.items():
        previous = STATE.ewma.get(field, value)
        ewma = EWMA_ALPHA * value + (1 - EWMA_ALPHA) * previous
        previous_deviation = STATE.ewma_deviation.get(field, 0.0)
        deviation = EWMA_ALPHA * abs(value - ewma) + (1 - EWMA_ALPHA) * previous_deviation
        STATE.ewma[field] = ewma
        STATE.ewma_deviation[field] = deviation


def _rolling_slope(values: list[float]) -> float:
    if len(values) < 4:
        return 0.0
    midpoint = len(values) // 2
    first_half = values[:midpoint]
    second_half = values[midpoint:]
    return (sum(second_half) / len(second_half)) - (sum(first_half) / len(first_half))


def analyze_metrics(signals: dict[str, float], recent: list[dict[str, Any]]) -> dict[str, set[str]]:
    metric_results = {field: set() for field in signals}

    for field, value in signals.items():
        baseline = BASELINES[field]
        previous_values = _metric_values(recent[:-1], field)

        if value >= baseline["soft_high"]:
            metric_results[field].add("soft_threshold")
        if value >= baseline["hard_high"]:
            metric_results[field].add("hard_threshold")

        if len(previous_values) >= 6:
            avg = sum(previous_values) / len(previous_values)
            stddev = _stddev(previous_values)
            if stddev > 0 and value > avg + 3 * stddev and value > baseline["normal_high"]:
                metric_results[field].add("rolling_z")

            q1 = _percentile(previous_values, 0.25)
            q3 = _percentile(previous_values, 0.75)
            iqr = q3 - q1
            if iqr > 0 and value > q3 + 1.5 * iqr and value > baseline["normal_high"]:
                metric_results[field].add("iqr_outlier")

        ewma = STATE.ewma.get(field, value)
        ewma_deviation = max(STATE.ewma_deviation.get(field, 0.0), 0.01)
        if value > ewma + 3 * ewma_deviation and value > baseline["normal_high"]:
            metric_results[field].add("ewma_deviation")
        if value >= ewma * 1.8 and value > baseline["normal_high"]:
            metric_results[field].add("ewma_deviation")

        values = _metric_values(recent, field)
        slope = _rolling_slope(values)
        if field == "memory_pct" and slope > 0.08 and value > baseline["normal_high"]:
            metric_results[field].add("rolling_slope")
            metric_results[field].add("ewma_trend")
        elif field != "memory_pct" and slope > baseline["normal_high"] * 0.5 and value > baseline["normal_high"]:
            metric_results[field].add("ewma_trend")

    return metric_results


def _has(metric_results: dict[str, set[str]], signal: str) -> bool:
    field, detector = signal.split(".", 1)
    return detector in metric_results.get(field, set())


def classify(payload: dict[str, Any]) -> tuple[str | None, str, str]:
    metrics = payload.get("metrics", {})
    logs = payload.get("logs", [])
    signals = _extract_metric_signals(metrics)
    payload["signals"] = signals
    STATE.window.append(payload)
    recent = list(STATE.window)

    metric_results = analyze_metrics(signals, recent)
    log_results = analyze_logs(logs)
    _update_ewma(signals)

    fault_detector_map = {
        "memory_leak": {
            "metric_signals": [
                "memory_pct.ewma_trend",
                "memory_pct.rolling_slope",
                "memory_pct.soft_threshold",
                "memory_pct.hard_threshold",
                "jvm_gc_pause_ms_avg.rolling_z",
                "jvm_gc_pause_ms_avg.ewma_deviation",
                "jvm_gc_pause_ms_avg.soft_threshold",
            ],
            "log_signals": ["memory_keywords", "error_signal"],
            "min_score": 3,
            "message": (
                f"Memory utilization {signals['memory_pct']:.0%}, "
                f"GC pause {signals['jvm_gc_pause_ms_avg']:.1f}ms, "
                f"CPU {signals['cpu_usage_percent']:.1f}%"
            ),
            "critical": signals["memory_pct"] >= 0.80 or signals["jvm_gc_pause_ms_avg"] >= 120,
        },
        "traffic_spike": {
            "metric_signals": [
                "http_requests_per_sec.rolling_z",
                "http_requests_per_sec.iqr_outlier",
                "http_requests_per_sec.ewma_deviation",
                "http_requests_per_sec.soft_threshold",
                "queue_depth.rolling_z",
                "queue_depth.iqr_outlier",
                "queue_depth.soft_threshold",
                "http_p99_latency_ms.ewma_deviation",
                "http_p99_latency_ms.soft_threshold",
                "cpu_usage_percent.ewma_deviation",
                "cpu_usage_percent.soft_threshold",
            ],
            "log_signals": ["traffic_keywords", "warning_signal"],
            "min_score": 3,
            "message": (
                f"RPS {signals['http_requests_per_sec']:.1f}, "
                f"queue depth {signals['queue_depth']:.0f}, "
                f"p99 latency {signals['http_p99_latency_ms']:.1f}ms"
            ),
            "critical": (
                signals["queue_depth"] >= 120
                or signals["http_p99_latency_ms"] >= 900
                or signals["http_5xx_rate"] >= 10
            ),
        },
        "dependency_timeout": {
            "metric_signals": [
                "upstream_timeout_rate.rolling_z",
                "upstream_timeout_rate.ewma_deviation",
                "upstream_timeout_rate.soft_threshold",
                "upstream_timeout_rate.hard_threshold",
                "http_5xx_rate.rolling_z",
                "http_5xx_rate.soft_threshold",
                "http_p99_latency_ms.rolling_z",
                "http_p99_latency_ms.ewma_deviation",
                "http_p99_latency_ms.soft_threshold",
            ],
            "log_signals": ["error_signal", "dependency_keywords"],
            "min_score": 3,
            "message": (
                f"Upstream timeout {signals['upstream_timeout_rate']:.1f}%, "
                f"5xx rate {signals['http_5xx_rate']:.1f}%, "
                f"p99 latency {signals['http_p99_latency_ms']:.1f}ms"
            ),
            "critical": (
                signals["upstream_timeout_rate"] >= 30
                or signals["http_5xx_rate"] >= 12
                or signals["http_p99_latency_ms"] >= 900
            ),
        },
    }

    best_type = None
    best_score = 0
    best_severity = "warning"
    best_message = ""
    for fault_type, config in fault_detector_map.items():
        metric_score = sum(1 for signal in config["metric_signals"] if _has(metric_results, signal))
        log_score = sum(1 for signal in config["log_signals"] if log_results[signal])
        score = metric_score + log_score
        if score > best_score:
            best_type = fault_type
            best_score = score
            best_severity = "critical" if config["critical"] else "warning"
            best_message = config["message"]

    min_score = fault_detector_map[best_type]["min_score"] if best_type else 999

    for fault_type in STATE.hit_counts:
        if fault_type == best_type and best_score >= min_score:
            STATE.hit_counts[fault_type] += 1
        else:
            STATE.hit_counts[fault_type] = 0

    if (
        best_type
        and STATE.hit_counts[best_type] >= CONSECUTIVE_HITS
        and best_type not in STATE.alerted_types
    ):
        STATE.alerted_types.add(best_type)
        return best_type, best_severity, best_message

    return None, "warning", ""


def write_alert(timestamp: str, fault_type: str, severity: str, message: str) -> None:
    alert = {
        "timestamp": timestamp,
        "type": fault_type,
        "severity": severity,
        "message": message,
    }
    with ALERTS_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(alert, ensure_ascii=True) + "\n")


class IngestHandler(BaseHTTPRequestHandler):
    server_version = "AIOpsPipeline/1.0"

    def do_POST(self) -> None:
        if self.path != "/ingest":
            self._send_json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length)
            payload = json.loads(raw_body)
            timestamp = payload["timestamp"]
            payload["metrics"]
            payload["logs"]
        except Exception as exc:
            self._send_json(400, {"error": f"invalid payload: {exc}"})
            return

        STATE.received += 1
        fault_type, severity, message = classify(payload)
        if fault_type:
            write_alert(timestamp, fault_type, severity, message)
            print(f"[ALERT] {fault_type} {severity}: {message}", flush=True)

        if STATE.received % 20 == 0:
            print(f"[PIPELINE] received={STATE.received}", flush=True)

        self._send_json(200, {"status": "ok"})

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "received": STATE.received})
            return
        self._send_json(404, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="AIOps W1 streaming anomaly pipeline")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reset-alerts", action="store_true")
    args = parser.parse_args()

    if args.reset_alerts:
        ALERTS_FILE.write_text("", encoding="utf-8")

    server = ThreadingHTTPServer((args.host, args.port), IngestHandler)
    print(f"[PIPELINE] listening on http://{args.host}:{args.port}/ingest", flush=True)
    print(f"[PIPELINE] alerts file: {ALERTS_FILE}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[PIPELINE] stopped", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
