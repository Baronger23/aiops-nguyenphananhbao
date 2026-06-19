import requests

alert_data = [
    {
      "labels": {
        "alertname": "MultiStepDeploy",
        "service": "api-gateway",
        "severity": "critical"
      },
      "annotations": {
        "summary": "Deploy failure on api-gateway",
        "description": "Triggering multi-step deploy"
      }
    }
]

resp = requests.post("http://localhost:9093/api/v2/alerts", json=alert_data)
print("Response status:", resp.status_code)
print("Response text:", resp.text)
