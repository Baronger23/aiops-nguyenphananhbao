import requests
import time

alert_data = [
    {
      "labels": {
        "alertname": "HighLatency",
        "service": "payment-svc",
        "severity": "warning"
      },
      "annotations": {
        "summary": "High latency on payment-svc",
        "description": "p99 latency is 600ms on payment-svc"
      }
    },
    {
      "labels": {
        "alertname": "HighLatency",
        "service": "inventory-svc",
        "severity": "warning"
      },
      "annotations": {
        "summary": "High latency on inventory-svc",
        "description": "p99 latency is 600ms on inventory-svc"
      }
    }
]

# Post both alerts simultaneously
resp = requests.post("http://localhost:9093/api/v2/alerts", json=alert_data)
print("Response status:", resp.status_code)

# Immediately sleep 2 seconds and post a DUPLICATE alert on payment-svc
time.sleep(2)
duplicate_alert = [
    {
      "labels": {
        "alertname": "HighLatency",
        "service": "payment-svc",
        "severity": "warning"
      },
      "annotations": {
        "summary": "High latency on payment-svc (duplicate)",
        "description": "p99 latency is 600ms on payment-svc"
      }
    }
]
resp2 = requests.post("http://localhost:9093/api/v2/alerts", json=duplicate_alert)
print("Duplicate alert status:", resp2.status_code)
