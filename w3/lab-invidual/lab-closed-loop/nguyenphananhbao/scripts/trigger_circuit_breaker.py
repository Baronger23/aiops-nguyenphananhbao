import subprocess
import time
import re

def log_contains(pattern):
    try:
        with open("orchestrator_test.log", "r", encoding="utf8") as f:
            content = f.read()
            return len(re.findall(pattern, content))
    except Exception:
        return 0

print("First crash injected. Waiting for first rollback to complete...")
while True:
    count = log_contains("ROLLBACK_EXECUTED")
    if count >= 1:
        print("First rollback complete.")
        break
    time.sleep(5)

print("Injecting second crash...")
subprocess.run(["bash", "../data-pack/scripts/inject_fault.sh", "kill", "checkout-svc"])
print("Waiting for second rollback to complete...")
while True:
    count = log_contains("ROLLBACK_EXECUTED")
    if count >= 2:
        print("Second rollback complete.")
        break
    time.sleep(5)

print("Injecting third crash...")
subprocess.run(["bash", "../data-pack/scripts/inject_fault.sh", "kill", "checkout-svc"])
print("Waiting for circuit breaker to halt...")
while True:
    if log_contains("CIRCUIT_BREAKER_HALT") or log_contains("CIRCUIT_open"):
        print("Circuit breaker successfully tripped!")
        break
    time.sleep(5)
