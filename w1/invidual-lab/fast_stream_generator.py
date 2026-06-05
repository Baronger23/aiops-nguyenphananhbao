#!/usr/bin/env python3
"""Fast test generator for the AIOps W1 lab.

This keeps the same payload shape and fault injection behavior as the provided
student/stream_generator.py, but lets you start the fault much sooner for demos.
It is only a local testing helper; keep using the original generator for the lab.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import request
import json
import random


ORIGINAL_GENERATOR = Path(__file__).parent / "student" / "stream_generator.py"


def load_original_generator():
    spec = importlib.util.spec_from_file_location("stream_generator", ORIGINAL_GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {ORIGINAL_GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def post_json(target: str, payload: dict) -> int:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        target,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=2) as response:
        response.read()
        return response.status


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast AIOps streaming data generator")
    parser.add_argument("--birthday", required=True, help="Student birthday YYYY-MM-DD")
    parser.add_argument("--target", default="http://localhost:8000/ingest")
    parser.add_argument("--speed", type=int, default=10)
    parser.add_argument(
        "--fault-start-seconds",
        type=float,
        default=10.0,
        help="Start fault after this many real-time seconds",
    )
    parser.add_argument(
        "--fault-type",
        choices=["memory_leak", "traffic_spike", "dependency_timeout"],
        default=None,
        help="Override birthday-derived fault type for testing",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=80,
        help="Stop after this many datapoints. Use 0 to run forever.",
    )
    args = parser.parse_args()

    gen = load_original_generator()
    params = gen.compute_fault_params(args.birthday)
    fault_type = args.fault_type or params["fault_type"]
    fault_start_real = args.fault_start_seconds

    print(f"[FAST GENERATOR] Birthday: {args.birthday}")
    print(f"[FAST GENERATOR] Fault type: {fault_type}")
    print(f"[FAST GENERATOR] Fault starts at: {fault_start_real:.1f}s real-time")
    print(f"[FAST GENERATOR] Target: {args.target}")
    print(f"[FAST GENERATOR] Speed: {args.speed}x (1 POST every {30 / args.speed:.1f}s)")
    print("---")

    rng = random.Random(gen.seed_from_birthday(args.birthday))
    interval = 30.0 / args.speed
    start_real = time.time()
    tick = 0
    fault_announced = False

    while args.max_ticks == 0 or tick < args.max_ticks:
        elapsed_real = time.time() - start_real
        t_prod_seconds = elapsed_real * args.speed
        t_prod_hours = t_prod_seconds / 3600.0
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

        metrics = gen.generate_baseline(rng, t_prod_hours)
        fault_active = elapsed_real >= fault_start_real

        if fault_active and not fault_announced:
            fault_announced = True
            print(
                f"\n[FAST FAULT INJECTED] type={fault_type} "
                f"at t_real={elapsed_real:.1f}s t_prod={t_prod_hours:.3f}h"
            )

        if fault_active:
            t_since_fault = (elapsed_real - fault_start_real) * args.speed / 3600.0
            metrics = gen.FAULT_INJECTORS[fault_type](metrics, rng, t_since_fault)

        logs = gen.generate_logs(rng, t_prod_hours, metrics, fault_active, fault_type, timestamp)
        payload = {"timestamp": timestamp, "metrics": metrics, "logs": logs}

        try:
            status = post_json(args.target, payload)
            if status != 200:
                print(f"[WARN] Endpoint returned {status}", file=sys.stderr)
        except Exception as exc:
            print(f"[WARN] POST failed: {exc}", file=sys.stderr)

        tick += 1
        if tick % 10 == 0:
            print(
                f"[FAST HEARTBEAT] Sent {tick} datapoints | "
                f"t_prod={t_prod_hours:.3f}h | fault_injected={fault_active}"
            )

        time.sleep(interval)


if __name__ == "__main__":
    main()
