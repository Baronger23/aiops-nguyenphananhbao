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
        "description": "p99 latency is 600ms on service payment-svc"
      }
    }
]

resp = requests.post("http://localhost:9093/api/v2/alerts", json=alert_data)
print("Response status:", resp.status_code)
print("Response text:", resp.text)
