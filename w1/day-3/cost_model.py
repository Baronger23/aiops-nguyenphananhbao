from __future__ import annotations

import json
import sys
from pathlib import Path


RESULTS_DIR = Path("results")
JSON_PATH = RESULTS_DIR / "cost_estimate.json"
MD_PATH = RESULTS_DIR / "cost_estimate.md"

TIERS = [
    {"tier": "Small", "services": 10, "log_gb_day": 50, "metric_eps": 100_000},
    {"tier": "Medium", "services": 100, "log_gb_day": 500, "metric_eps": 1_000_000},
    {"tier": "Large", "services": 1000, "log_gb_day": 5120, "metric_eps": 10_000_000},
]


def estimate_tier(tier: dict) -> dict:
    log_gb_month = tier["log_gb_day"] * 30
    metric_billion_events_month = tier["metric_eps"] * 86_400 * 30 / 1_000_000_000

    # Self-host estimate: S3/Loki/VM storage, Kafka/Flink/collector compute, cross-AZ traffic.
    storage_cost = log_gb_month * 0.045 + metric_billion_events_month * 0.65
    compute_cost = tier["services"] * 18 + tier["metric_eps"] / 100_000 * 240 + tier["log_gb_day"] * 1.1
    network_cost = tier["log_gb_day"] * 30 * 0.02 + metric_billion_events_month * 0.08
    self_host_total = storage_cost + compute_cost + network_cost

    # Datadog-style SaaS estimate: infra hosts, log ingest/index, custom metrics/events.
    datadog_infra_cost = tier["services"] * 18
    datadog_log_cost = tier["log_gb_day"] * 30 * 0.25
    datadog_metric_cost = metric_billion_events_month * 1.35
    datadog_total = datadog_infra_cost + datadog_log_cost + datadog_metric_cost

    return {
        "tier": tier["tier"],
        "services": tier["services"],
        "logs_per_day": f'{tier["log_gb_day"]} GB',
        "metric_events_sec": tier["metric_eps"],
        "storage_cost": round(storage_cost, 2),
        "compute_cost": round(compute_cost, 2),
        "network_cost": round(network_cost, 2),
        "self_host_total": round(self_host_total, 2),
        "datadog_total": round(datadog_total, 2),
    }


def markdown_table(rows: list[dict]) -> str:
    headers = [
        "Quy mô",
        "Số service",
        "Log/ngày",
        "Metric EPS",
        "Lưu trữ",
        "Tính toán",
        "Mạng",
        "Tổng self-host",
        "Tổng Datadog",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["tier"],
                    str(row["services"]),
                    row["logs_per_day"],
                    f'{row["metric_events_sec"]:,}',
                    f'${row["storage_cost"]:,.2f}',
                    f'${row["compute_cost"]:,.2f}',
                    f'${row["network_cost"]:,.2f}',
                    f'${row["self_host_total"]:,.2f}',
                    f'${row["datadog_total"]:,.2f}',
                ]
            )
            + " |"
        )

    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    rows = [estimate_tier(tier) for tier in TIERS]
    table = markdown_table(rows)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    MD_PATH.write_text(table + "\n", encoding="utf-8")

    print(table)
    print(f"\nWrote {JSON_PATH} and {MD_PATH}")


if __name__ == "__main__":
    main()
