import requests

alert_data = [
    {
      "labels": {
        "alertname": "TestHallucination",
        "service": "payment-svc",
        "severity": "critical"
      },
      "annotations": {
        "summary": "Hallucination alert",
        "description": "Triggering hallucination defense test"
      }
    }
]

resp = requests.post("http://localhost:9093/api/v2/alerts", json=alert_data)
print("Response status:", resp.status_code)
