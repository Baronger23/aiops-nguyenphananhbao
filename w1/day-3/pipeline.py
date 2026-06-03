from __future__ import annotations

import json
import math
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path


WINDOW_SIZE = 5
RESULTS_DIR = Path("results")
FEATURES_PATH = RESULTS_DIR / "features.json"


def mock_metric_stream(total_events: int = 60) -> list[dict]:
    """Fake queue records for a payment-service metric stream."""
    start = datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc)
    stream = []

    for i in range(total_events):
        latency = 120 + 12 * math.sin(i / 4) + (i % 7) * 2
        error_rate = 0.003 + (i % 5) * 0.0005
        throughput = 900 + (i % 10) * 18

        # Simulate a checkout dependency incident: latency and errors rise fast.
        if 36 <= i <= 44:
            latency += 130 + (i - 36) * 18
            error_rate += 0.035 + (i - 36) * 0.004
            throughput -= 160

        stream.append(
            {
                "timestamp": (start + timedelta(seconds=i * 10)).isoformat(),
                "service": "payment-service",
                "latency_ms": round(latency, 2),
                "error_rate": round(error_rate, 5),
                "throughput": int(throughput),
            }
        )

    return stream


def mean(values: deque[float]) -> float:
    return sum(values) / len(values)


def extract_features(events: list[dict], window_size: int = WINDOW_SIZE) -> list[dict]:
    latency_window: deque[float] = deque(maxlen=window_size)
    error_window: deque[float] = deque(maxlen=window_size)
    features = []
    previous = None

    for event in events:
        latency = float(event["latency_ms"])
        error_rate = float(event["error_rate"])

        latency_window.append(latency)
        error_window.append(error_rate)

        if previous is None:
            latency_rate_of_change = 0.0
            error_rate_of_change = 0.0
        else:
            latency_rate_of_change = latency - float(previous["latency_ms"])
            error_rate_of_change = error_rate - float(previous["error_rate"])

        features.append(
            {
                **event,
                "rolling_mean_latency": round(mean(latency_window), 2),
                "rate_of_change_latency": round(latency_rate_of_change, 2),
                "rolling_mean_error_rate": round(mean(error_window), 5),
                "rate_of_change_error_rate": round(error_rate_of_change, 5),
            }
        )
        previous = event

    return features


def write_features(features: list[dict]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    FEATURES_PATH.write_text(json.dumps(features, indent=2), encoding="utf-8")


def main() -> None:
    queue = mock_metric_stream()
    features = extract_features(queue)
    write_features(features)

    print(f"Read {len(queue)} metric events from fake queue.")
    print(f"Extracted rolling/rate features with window={WINDOW_SIZE}.")
    print(f"Wrote {FEATURES_PATH}")
    print("\nLast 5 feature rows:")
    for row in features[-5:]:
        print(
            {
                "timestamp": row["timestamp"],
                "latency_ms": row["latency_ms"],
                "rolling_mean_latency": row["rolling_mean_latency"],
                "rate_of_change_latency": row["rate_of_change_latency"],
                "rolling_mean_error_rate": row["rolling_mean_error_rate"],
                "rate_of_change_error_rate": row["rate_of_change_error_rate"],
            }
        )


if __name__ == "__main__":
    main()
