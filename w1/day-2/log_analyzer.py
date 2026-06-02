from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig


def parse_hdfs_line(line: str) -> tuple[pd.Timestamp, str]:
    parts = line.strip().split(maxsplit=4)
    if len(parts) >= 5:
        timestamp = pd.to_datetime(parts[0] + parts[1], format="%y%m%d%H%M%S", errors="coerce")
        return timestamp, parts[4]
    return pd.NaT, line.strip()


def build_miner(sim_th: float = 0.5) -> TemplateMiner:
    config = TemplateMinerConfig()
    config.drain_sim_th = sim_th
    config.drain_depth = 4
    config.profiling_enabled = False
    return TemplateMiner(config=config)


def parse_logs(log_path: Path, sim_th: float = 0.5) -> pd.DataFrame:
    miner = build_miner(sim_th)
    rows = []

    with log_path.open("r", encoding="utf-8", errors="ignore") as file:
        for raw_log in file:
            raw_log = raw_log.rstrip("\n")
            timestamp, message = parse_hdfs_line(raw_log)
            result = miner.add_log_message(message)
            rows.append(
                {
                    "timestamp": timestamp,
                    "raw_log": raw_log,
                    "template_id": result["cluster_id"],
                    "template": result["template_mined"],
                }
            )

    parsed = pd.DataFrame(rows)
    final_templates = {cluster.cluster_id: cluster.get_template() for cluster in miner.drain.clusters}
    parsed["template"] = parsed["template_id"].map(final_templates)
    return parsed


def find_last_hour_spikes(parsed: pd.DataFrame) -> pd.DataFrame:
    parsed = parsed.dropna(subset=["timestamp"]).copy()
    if parsed.empty:
        return pd.DataFrame(columns=["template_id", "template", "last_hour_count", "baseline_mean", "z_score"])

    end_time = parsed["timestamp"].max()
    last_hour_start = end_time - pd.Timedelta(hours=1)
    historical = parsed[parsed["timestamp"] < last_hour_start]
    last_hour = parsed[parsed["timestamp"] >= last_hour_start]

    if historical.empty or last_hour.empty:
        return pd.DataFrame(columns=["template_id", "template", "last_hour_count", "baseline_mean", "z_score"])

    hourly = (
        historical.groupby([pd.Grouper(key="timestamp", freq="1h"), "template_id"])
        .size()
        .unstack(fill_value=0)
    )
    last_counts = last_hour.groupby("template_id").size()
    template_lookup = parsed.drop_duplicates("template_id").set_index("template_id")["template"]

    rows = []
    for template_id, last_count in last_counts.items():
        if template_id not in hourly.columns:
            continue
        baseline = hourly[template_id]
        mean = baseline.mean()
        std = baseline.std(ddof=0)
        z_score = (last_count - mean) / std if std > 0 else 0.0
        if last_count > mean + 3 * std and last_count >= 5:
            rows.append(
                {
                    "template_id": template_id,
                    "template": template_lookup.get(template_id, ""),
                    "last_hour_count": int(last_count),
                    "baseline_mean": round(float(mean), 2),
                    "z_score": round(float(z_score), 2),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["template_id", "template", "last_hour_count", "baseline_mean", "z_score"])

    return pd.DataFrame(rows).sort_values("z_score", ascending=False)


def find_new_templates_last_hour(parsed: pd.DataFrame) -> pd.DataFrame:
    parsed = parsed.dropna(subset=["timestamp"]).copy()
    if parsed.empty:
        return pd.DataFrame(columns=["template_id", "template", "first_seen"])

    end_time = parsed["timestamp"].max()
    last_hour_start = end_time - pd.Timedelta(hours=1)
    historical_templates = set(parsed.loc[parsed["timestamp"] < last_hour_start, "template"])
    recent = parsed[parsed["timestamp"] >= last_hour_start]
    new_templates = recent[~recent["template"].isin(historical_templates)]

    if new_templates.empty:
        return pd.DataFrame(columns=["template_id", "template", "first_seen"])

    return (
        new_templates.groupby(["template_id", "template"], as_index=False)["timestamp"]
        .min()
        .rename(columns={"timestamp": "first_seen"})
        .sort_values("first_seen")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Mini Drain3 log analyzer")
    parser.add_argument("logfile", type=Path, help="Path to a log file")
    args = parser.parse_args()

    parsed = parse_logs(args.logfile)
    total_lines = len(parsed)
    unique_templates = parsed["template_id"].nunique()
    top_templates = Counter(parsed["template_id"]).most_common(5)
    template_lookup = parsed.drop_duplicates("template_id").set_index("template_id")["template"]

    print(f"Log file: {args.logfile}")
    print(f"Total log lines: {total_lines}")
    print(f"Unique templates: {unique_templates}")
    print()
    print("Top-5 templates:")
    for template_id, count in top_templates:
        percent = count / total_lines * 100 if total_lines else 0
        print(f"- T{template_id}: {count} lines ({percent:.2f}%) | {template_lookup.get(template_id, '')}")

    print()
    print("Template spikes in the last 1 hour:")
    spikes = find_last_hour_spikes(parsed)
    if spikes.empty:
        print("- None detected with 3-sigma rule.")
    else:
        for row in spikes.itertuples(index=False):
            print(
                f"- T{row.template_id}: count={row.last_hour_count}, "
                f"baseline_mean={row.baseline_mean}, z={row.z_score} | {row.template}"
            )

    print()
    print("New templates in the last 1 hour:")
    new_templates = find_new_templates_last_hour(parsed)
    if new_templates.empty:
        print("- None detected.")
    else:
        for row in new_templates.itertuples(index=False):
            print(f"- T{row.template_id}: first_seen={row.first_seen} | {row.template}")


if __name__ == "__main__":
    main()
