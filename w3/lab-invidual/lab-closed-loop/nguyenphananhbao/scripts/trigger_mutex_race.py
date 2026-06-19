import requests

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
        "alertname": "HighErrorRate",
        "service": "payment-svc",
        "severity": "critical"
      },
      "annotations": {
        "summary": "High error rate on payment-svc",
        "description": "Error rate > 10% on payment-svc"
      }
    }
]

resp = requests.post("http://localhost:9093/api/v2/alerts", json=alert_data)
print("Response status:", resp.status_code)
