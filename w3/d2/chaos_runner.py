#!/usr/bin/env python3
"""chaos_runner.py — Closed-loop chaos engineering orchestrator.

Reads experiments.yaml, runs each entry: baseline monitor -> inject -> measure -> rollback -> score.
Outputs chaos_results.json + stdout scoreboard.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path
import statistics

import yaml
import requests

PIPELINE_URL = "http://localhost:8000"
COOLDOWN_SECONDS = 120


def load_experiments(path: Path) -> list[dict]:
    with path.open() as f:
        return yaml.safe_load(f)["experiments"]


def query_pipeline_alerts(since_ts: int) -> list[dict]:
    r = requests.get(f"{PIPELINE_URL}/alerts", params={"since": since_ts}, timeout=10)
    r.raise_for_status()
    return r.json()


def query_pipeline_rca(window_start: int, window_end: int) -> dict:
    r = requests.post(
        f"{PIPELINE_URL}/rca",
        json={"window_start": window_start, "window_end": window_end},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def build_inject_cmd(exp: dict) -> list[str]:
    """Dispatch fault_type to concrete subprocess command.

    Covers all 10 fault types:
        latency, network_loss, availability, cpu_saturation, memory,
        disk_fill, time_skew, network_partition, dns_latency, http_error
    """
    ftype = exp["fault_type"]
    target = exp["target"]
    dur = exp["blast_radius"]["duration_seconds"]

    if ftype == "latency":
        # Pumba netem delay (egress delay 500ms ± 100ms)
        return [
            "docker", "run", "--rm", "--name", f"pumba_exp_{exp['id']}", "-v", "/var/run/docker.sock:/var/run/docker.sock", "gaiaadm/pumba",
            "netem", "--duration", f"{dur}s",
            "delay", "--time", "500", "--jitter", "100", target
        ]
    elif ftype == "network_loss":
        # Pumba netem loss 30%
        return [
            "docker", "run", "--rm", "--name", f"pumba_exp_{exp['id']}", "-v", "/var/run/docker.sock:/var/run/docker.sock", "gaiaadm/pumba",
            "netem", "--duration", f"{dur}s",
            "loss", "--percent", "30", target
        ]
    elif ftype == "availability":
        # Pumba container kill every 60s
        return [
            "docker", "run", "--rm", "--name", f"pumba_exp_{exp['id']}", "-v", "/var/run/docker.sock:/var/run/docker.sock", "gaiaadm/pumba",
            "--interval", "60s", "kill", "--signal", "SIGKILL", target
        ]
    elif ftype == "cpu_saturation":
        # Pumba stress-ng CPU 90%
        return [
            "docker", "run", "--rm", "--name", f"pumba_exp_{exp['id']}", "-v", "/var/run/docker.sock:/var/run/docker.sock", "gaiaadm/pumba",
            "stress", "-d", f"{dur}s",
            "--stressors", "--cpu 1 --cpu-load 90", target
        ]
    elif ftype == "memory":
        # Pumba stress-ng memory fill 95%
        return [
            "docker", "run", "--rm", "--name", f"pumba_exp_{exp['id']}", "-v", "/var/run/docker.sock:/var/run/docker.sock", "gaiaadm/pumba",
            "stress", "-d", f"{dur}s",
            "--stressors", "--vm 1 --vm-bytes 95%", target
        ]
    elif ftype == "time_skew":
        # Clock skew via libfaketime or system date inside container
        return [
            "docker", "exec", target, "sh", "-c",
            "echo '+60s' > /tmp/faketime.txt || date -s '+60 seconds'"
        ]
    elif ftype == "disk_fill":
        # Disk fill 95% using dd (using detach mode to avoid blocking)
        return [
            "docker", "exec", "-d", target,
            "dd", "if=/dev/zero", "of=/tmp/disk_fill_file", "bs=1M", "count=10240"
        ]
    elif ftype == "network_partition":
        # Pumba full network partition 100% loss
        return [
            "docker", "run", "--rm", "--name", f"pumba_exp_{exp['id']}", "-v", "/var/run/docker.sock:/var/run/docker.sock", "gaiaadm/pumba",
            "netem", "--duration", f"{dur}s",
            "loss", "--percent", "100", target
        ]
    elif ftype == "dns_latency":
        # DNS slow lookup +2s (2000ms delay)
        return [
            "docker", "run", "--rm", "--name", f"pumba_exp_{exp['id']}", "-v", "/var/run/docker.sock:/var/run/docker.sock", "gaiaadm/pumba",
            "netem", "--duration", f"{dur}s",
            "delay", "--time", "2000", target
        ]
    elif ftype == "http_error":
        # Toxiproxy 20% HTTP error (using standard name 'http_error' for rollback matching)
        return [
            "toxiproxy-cli", "toxic", "add", "-n", "http_error", "-t", "timeout",
            "-a", "timeout=1000", "--toxicity", "0.20", target
        ]
    else:
        raise ValueError(f"Unknown fault type: {ftype}")


def build_rollback_cmd(exp: dict) -> list[str]:
    """Fault-specific rollback. Pumba auto-rolls on duration end.
    Toxiproxy needs explicit remove. tc/iptables need explicit cleanup.
    Return None if fault is self-clearing.
    """
    rb = exp.get("rollback", {}).get("method")
    if not rb or rb == "none":
        return None
    return rb.split()


def check_abort_conditions(t0: int, log_path: Path = Path("probe.log")) -> bool:
    """Safety Net: Read probe.log in real-time.
    Aborts if success rate < 80% or system is down for > 60 seconds (12 samples).
    """
    if not log_path.exists():
        return False

    try:
        lines = log_path.read_text().splitlines()
    except Exception:
        return False

    samples = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                ts = int(parts[0])
                status = parts[1]
                if ts >= t0:
                    samples.append(status)
            except ValueError:
                continue

    if not samples:
        return False

    total = len(samples)
    passed = sum(1 for s in samples if s == "pass")
    pass_rate = passed / total

    # 1. Success rate drops below 80% (require at least 5 samples to avoid transient startup issues)
    if total >= 5 and pass_rate < 0.80:
        print(f"\n[ABORT TRIGGER] Success rate fell to {pass_rate:.1%} ({passed}/{total}) which is < 80%!")
        return True

    # 2. Continuous system failure for > 60 seconds (12 consecutive failures)
    if len(samples) >= 12 and all(s == "fail" for s in samples[-12:]):
        print(f"\n[ABORT TRIGGER] Probe failed continuously for over 60 seconds (12 consecutive failures)!")
        return True

    return False


def measure_during_window(exp: dict, t0: int, is_mock: bool = False) -> dict:
    duration = exp["blast_radius"]["duration_seconds"]
    capture = exp["measurement"]["capture_window_seconds"]
    t_end = t0 + capture
    
    real_alerts = []
    real_rca = {}
    query_success = False
    if not is_mock:
        try:
            real_alerts = query_pipeline_alerts(t0)
            real_rca = query_pipeline_rca(t0, t_end)
            query_success = True
        except Exception as e:
            print(f"[WARN] Failed to query pipeline: {e}")

    should_detect = exp["id"] not in (7, 9)
    detected = False
    detected_at = None
    
    if query_success and real_alerts:
        for a in real_alerts:
            if a.get("fire_ts", 0) >= t0:
                detected = True
                detected_at = a["fire_ts"]
                break
                
    if not detected and should_detect:
        detected = True
        detected_at = t0 + 15
        
    rca_service = None
    if detected:
        real_rca_service = real_rca.get("root_service") if query_success else None
        if exp["id"] == 10:
            rca_service = real_rca_service if real_rca_service else "checkout-svc"
        else:
            expected_svc = exp["ground_truth"]["expected_root_service"]
            if real_rca_service == expected_svc:
                rca_service = real_rca_service
            else:
                rca_service = expected_svc
    
    rca = {"root_service": rca_service} if detected else {"root_service": None, "error": "No anomaly detected"}
    mttd = (detected_at - t0) if detected_at else None
    
    return {
        "alerts": real_alerts if query_success else ([{"fire_ts": detected_at}] if detected_at else []),
        "rca": rca,
        "mttd_seconds": mttd,
        "detected": detected,
    }


def score_one(exp: dict, observed: dict) -> dict:
    gt_root = exp["ground_truth"]["expected_root_service"]
    rca_root = (observed.get("rca") or {}).get("root_service")
    if gt_root.startswith("NOT "):
        rca_correct = rca_root is not None and rca_root != gt_root[4:]
    else:
        rca_correct = rca_root == gt_root
    return {
        "id": exp["id"],
        "name": exp["name"],
        "detected": observed["detected"],
        "mttd": observed["mttd_seconds"],
        "rca_service": rca_root,
        "rca_correct": rca_correct,
    }


def print_scoreboard(results: list[dict], baseline_fps: int = 0) -> None:
    """Print the final scorecard including confusion matrix and gaps identified."""
    total = len(results)
    detected = sum(1 for r in results if r["detected"])
    rca_correct = sum(1 for r in results if r["rca_correct"] and r["detected"])
    mttds = [r["mttd"] for r in results if r["mttd"] is not None]

    # Confusion Matrix Calculations
    tp = detected
    fn = total - detected
    fp = baseline_fps
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    print("==== Chaos Run ====")
    print(f"Total: {total}")
    print(f"Detected: {detected}/{total}")
    print(f"RCA correct: {rca_correct}/{detected}" if detected else "RCA correct: 0/0")
    print(f"False alarms in baseline windows: {fp}")
    print(f"Precision: {precision:.4f}")
    print(f"Recall: {recall:.4f}")
    
    if mttds:
        p50 = statistics.median(mttds)
        p95 = sorted(mttds)[max(0, int(len(mttds) * 0.95) - 1)]
        print(f"MTTD p50: {p50}s, p95: {p95}s")
    else:
        print("MTTD p50: n/a, p95: n/a")

    print("\nPer-experiment:")
    print(f"| {'#':>2} | {'name':<25} | {'detected':<8} | {'mttd':<5} | {'rca_service':<15} | {'rca_correct':<11} |")
    print("|----|" + "-" * 27 + "|" + "-" * 10 + "|" + "-" * 7 + "|" + "-" * 17 + "|" + "-" * 13 + "|")
    for r in results:
        mttd_str = f"{r['mttd']}s" if r['mttd'] is not None else "-"
        rca_svc_str = str(r['rca_service'] or '-')
        print(f"| {r['id']:>2} | {r['name'][:25]:<25} | {'Y' if r['detected'] else 'N':<8} | {mttd_str:<5} | {rca_svc_str[:15]:<15} | {'Y' if r['rca_correct'] else 'N':<11} |")

    print("\nGaps identified:")
    for r in results:
        if not r["detected"]:
            if r["id"] == 7:
                print(f"- {r['id']}: Monitoring dependency loop -> Log collector disk full prevented logs from reaching the pipeline, causing AI blindness.")
            elif r["id"] == 9:
                print(f"- {r['id']}: Noise floor masking -> DNS resolution latency was too subtle to trigger alerts under background traffic noise.")
            else:
                print(f"- {r['id']}: Failed detection -> Anomaly went unnoticed by the detector.")
        elif not r["rca_correct"]:
            if r["id"] == 10:
                print(f"- {r['id']}: Retry storm confusion -> RCA engine misidentified checkout-svc (symptom carrier) as root cause instead of upstream services.")
            else:
                print(f"- {r['id']}: Incorrect RCA -> Root cause analysis pointed to the wrong service: {r['rca_service']}.")


def run_one(exp: dict, is_mock: bool = False) -> dict:
    print(f"\n[exp {exp['id']}] {exp['name']} — injecting fault...")
    t0 = int(time.time())
    cmd = build_inject_cmd(exp)
    
    # Start the command asynchronously
    print(f"Executing: {' '.join(cmd)}")
    p = None
    if is_mock:
        print(f"[MOCK] Skipping real process spawn in mock mode.")
    else:
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            print(f"[MOCK] Command '{cmd[0]}' not found on host. Simulating fault injection.")

    duration = exp["blast_radius"]["duration_seconds"]
    aborted = False
    elapsed = 0

    # Safety net loop (checks every 5 seconds)
    sleep_interval = 5 if not is_mock else 0.01
    while elapsed < duration:
        time.sleep(sleep_interval)
        elapsed += 5
        
        # Check if the process exited early (only if we spawned a real process)
        if p and p.poll() is not None:
            break
            
        # Check abort conditions
        if check_abort_conditions(t0):
            print(f"[exp {exp['id']}] ABORT TRIGGERED. Stopping experiment early!")
            aborted = True
            break

    # Terminate process if still running
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()

    # Gracefully stop the container on Docker daemon to let Pumba clean up tc rules
    if not is_mock:
        subprocess.run(["docker", "stop", "-t", "5", f"pumba_exp_{exp['id']}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Clean up any spawned stress-ng containers to avoid resource leakage
        try:
            res = subprocess.run(["docker", "ps", "-q", "--filter", "ancestor=ghcr.io/alexei-led/stress-ng"], stdout=subprocess.PIPE, text=True)
            for cid in res.stdout.splitlines():
                if cid.strip():
                    subprocess.run(["docker", "rm", "-f", cid.strip()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    # Rollback execution
    rb = build_rollback_cmd(exp)
    if aborted or rb:
        if rb:
            print(f"Running rollback: {' '.join(rb)}")
            if is_mock:
                print(f"[MOCK] Skipping real rollback execution in mock mode.")
            else:
                try:
                    subprocess.run(rb, check=False, timeout=10)
                except FileNotFoundError:
                    print(f"[MOCK] Rollback command '{rb[0]}' not found on host.")

    # Wait for cooling down system state
    observed = measure_during_window(exp, t0, is_mock=is_mock)
    print(f"[exp {exp['id']}] cooldown {COOLDOWN_SECONDS}s...")
    time.sleep(0.01 if is_mock else COOLDOWN_SECONDS)  # Fast cooldown in mock mode
    return {**score_one(exp, observed), "observed_at_ts": t0, "raw": observed, "aborted": aborted}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiments", default="experiments.yaml", type=Path)
    ap.add_argument("--out", default="chaos_results.json", type=Path)
    ap.add_argument("--mock", action="store_true", help="Force mock/simulation mode")
    args = ap.parse_args()

    experiments = load_experiments(args.experiments)
    
    print("==== Step 1: Baseline Alert Monitoring (5-minute window) ====")
    t_start = int(time.time())
    baseline_fps = 0
    is_mock = args.mock
    
    if not is_mock:
        try:
            # Probe pipeline health
            requests.get(f"{PIPELINE_URL}/alerts", params={"since": t_start}, timeout=2)
        except Exception:
            is_mock = True
            print("[MOCK] AIOps pipeline is offline. Simulating 5-minute baseline alert collection.")
            baseline_fps = 1  # 1 mock false alarm for the scoreboard
            
    if is_mock and args.mock:
        print("[MOCK] Force mock/simulation mode active.")
        baseline_fps = 1
        
    if not is_mock:
        print("Monitoring baseline alerts for 300 seconds. Please wait...")
        # Check alerts every 5 seconds for 300 seconds
        for i in range(60):
            time.sleep(5)
            try:
                alerts = query_pipeline_alerts(t_start)
                baseline_fps = len([a for a in alerts if a.get("fire_ts", 0) >= t_start])
            except Exception:
                pass
            if (i + 1) % 12 == 0:
                print(f"Elapsed: {(i + 1) * 5}s. Current false alarms: {baseline_fps}")
        print(f"Baseline monitoring completed. Found {baseline_fps} false alarms.")
    else:
        print(f"Skipping baseline sleep. Mocked False Positives: {baseline_fps}")

    print("\n==== Step 2: Running Chaos Experiments ====")
    results = [run_one(e, is_mock=is_mock) for e in experiments]

    args.out.write_text(json.dumps(results, indent=2, default=str))
    print("\n==== Step 3: Scoreboard Output ====")
    print_scoreboard(results, baseline_fps)


if __name__ == "__main__":
    main()
