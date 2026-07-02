import math
import time
from datetime import datetime
from fastapi.testclient import TestClient
from app import app, TENANT_CONFIGS, MOCK_DYNAMODB_AUDIT_STORE, MOCK_TENANT_ERROR_BUDGETS

client = TestClient(app)
tenant_id = "tnt-squad12-finance"

def get_base_payload(spend_value=50.0, idle_hours=0.0, cpu_util=30.0, env="dev", is_bypass=False, resource_id="notebook-instance-training-v2", fallback_context=None):
    """
    Helper function to generate a valid test payload.
    Ensures 14 days of CUR baseline history to pass the Holt-Winters warm-up check.
    """
    signals = []
    # 14 days of historical baseline
    for i in range(1, 15):
        signals.append({
            "ts": f"2026-06-{i:02d}T00:00:00Z",
            "signal_name": "daily_cur_spend_usd",
            "value": 50.0,
            "labels": {
                "resource_id": resource_id,
                "service": "SageMaker",
                "environment": env,
                "squad_owner": "squad-prediction"
            }
        })
        
    # Today's spend signal
    today_labels = {
        "resource_id": resource_id,
        "service": "SageMaker",
        "environment": env,
        "squad_owner": "squad-prediction"
    }
    if is_bypass:
        today_labels["FinOps_Bypass"] = True
    if fallback_context:
        today_labels["fallback_context"] = fallback_context

    signals.append({
        "ts": "2026-06-22T00:00:00Z",
        "signal_name": "daily_cur_spend_usd",
        "value": spend_value,
        "labels": today_labels
    })
    
    # Today's idle metric
    signals.append({
        "ts": "2026-06-22T00:00:00Z",
        "signal_name": "resource_utilization_metrics",
        "value": idle_hours,
        "labels": {
            "resource_id": resource_id,
            "metric_name": "idle_hours_continuous"
        }
    })
    
    # Today's CPU metric
    signals.append({
        "ts": "2026-06-22T00:00:00Z",
        "signal_name": "resource_utilization_metrics",
        "value": cpu_util,
        "labels": {
            "resource_id": resource_id,
            "metric_name": "cpu_utilization_percent"
        }
    })
    
    return {
        "signal_window": signals,
        "context": {
            "time_range": {
                "start_ts": "2026-06-21T00:00:00Z",
                "end_ts": "2026-06-22T00:00:00Z"
            }
        }
    }


def test_scenario_1_happy_path():
    """Scenario 1: Baseline / Happy Path (Normal operations, no alerts)."""
    payload = get_base_payload(spend_value=52.0, idle_hours=2.0, cpu_util=30.0)
    response = client.post(
        "/v1/detect", 
        json=payload, 
        headers={"X-Tenant-Id": tenant_id, "X-Idempotency-Key": "squad12_20260623_scen1"}
    )
    assert response.status_code == 202
    audit_id = response.json()["audit_id"]
    
    time.sleep(0.1)
    status_response = client.get(f"/v1/status/{audit_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "COMPLETED"
    assert status_response.json()["anomaly"] is False
    assert status_response.json()["suggested_action"] == "ALERT_ONLY"


def test_scenario_2_runaway_training_dev():
    """Scenario 2: Runaway Training Cluster in Dev (Triggers shutdown)."""
    payload = get_base_payload(spend_value=450.0, idle_hours=18.0, cpu_util=3.0, env="dev")
    response = client.post(
        "/v1/detect", 
        json=payload, 
        headers={"X-Tenant-Id": tenant_id, "X-Idempotency-Key": "squad12_20260623_scen2"}
    )
    assert response.status_code == 202
    audit_id = response.json()["audit_id"]
    
    time.sleep(0.1)
    status_response = client.get(f"/v1/status/{audit_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "COMPLETED"
    assert status_response.json()["anomaly"] is True
    assert status_response.json()["suggested_action"] == "SCHEDULE_SHUTDOWN"
    # Use ASCII check to avoid Windows console codepage/encoding mismatch
    assert "idle" in status_response.json()["reasoning"]
    
    # Assert generated AWS CLI command is correct for SageMaker in dev environment
    details = status_response.json()["details"]
    assert details["aws_cli_command"] is not None
    assert "aws sagemaker stop-notebook-instance" in details["aws_cli_command"]


def test_scenario_3_prod_safety_guard():
    """Scenario 3: Anomaly on Prod environment (Gated to TAG_FOR_REVIEW instead of shutdown)."""
    payload = get_base_payload(spend_value=450.0, idle_hours=18.0, cpu_util=3.0, env="prod")
    response = client.post(
        "/v1/detect", 
        json=payload, 
        headers={"X-Tenant-Id": tenant_id, "X-Idempotency-Key": "squad12_20260623_scen3"}
    )
    assert response.status_code == 202
    audit_id = response.json()["audit_id"]
    
    time.sleep(0.1)
    status_response = client.get(f"/v1/status/{audit_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "COMPLETED"
    assert status_response.json()["anomaly"] is True
    assert status_response.json()["suggested_action"] == "TAG_FOR_REVIEW"
    
    # Assert generated AWS CLI command is None for production
    details = status_response.json()["details"]
    assert details["aws_cli_command"] is None


def test_scenario_4_whitelist_bypass():
    """Scenario 4: Whitelist Bypass Tag set (Gated to ALERT_ONLY)."""
    payload = get_base_payload(spend_value=450.0, idle_hours=18.0, cpu_util=3.0, env="dev", is_bypass=True)
    response = client.post(
        "/v1/detect", 
        json=payload, 
        headers={"X-Tenant-Id": tenant_id, "X-Idempotency-Key": "squad12_20260623_scen4"}
    )
    assert response.status_code == 202
    audit_id = response.json()["audit_id"]
    
    time.sleep(0.1)
    status_response = client.get(f"/v1/status/{audit_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "COMPLETED"
    assert status_response.json()["suggested_action"] == "ALERT_ONLY"
    # Use ASCII check to avoid Windows console codepage/encoding mismatch
    assert "FinOps_Bypass" in status_response.json()["reasoning"]


def test_scenario_5_business_growth():
    """Scenario 5: High cost spike but High CPU utilization (Classified as Business Growth, ALERT_ONLY)."""
    payload = get_base_payload(spend_value=450.0, idle_hours=0.0, cpu_util=95.0, env="dev")
    response = client.post(
        "/v1/detect", 
        json=payload, 
        headers={"X-Tenant-Id": tenant_id, "X-Idempotency-Key": "squad12_20260623_scen5"}
    )
    assert response.status_code == 202
    audit_id = response.json()["audit_id"]
    
    time.sleep(0.1)
    status_response = client.get(f"/v1/status/{audit_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "COMPLETED"
    assert status_response.json()["suggested_action"] == "ALERT_ONLY"
    # Use ASCII check to avoid Windows console codepage/encoding mismatch
    assert "CPU" in status_response.json()["reasoning"]


def test_scenario_6_fallback_spawning():
    """Scenario 6: Fallback Cost item (Triggers dynamic node spawning for specific VPC)."""
    payload = get_base_payload(
        spend_value=450.0, 
        idle_hours=0.0, 
        cpu_util=30.0, 
        env="dev", 
        resource_id="service-level-aggregate",
        fallback_context={"vpc_id": "vpc-0abcdef", "cost_category": "DataTransfer"}
    )
    response = client.post(
        "/v1/detect", 
        json=payload, 
        headers={"X-Tenant-Id": tenant_id, "X-Idempotency-Key": "squad12_20260623_scen6"}
    )
    assert response.status_code == 202
    audit_id = response.json()["audit_id"]
    
    time.sleep(0.1)
    status_response = client.get(f"/v1/status/{audit_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "COMPLETED"
    assert status_response.json()["details"]["affected_resource"] == "service-level-aggregate:vpc-0abcdef"
    # Use ASCII check to avoid Windows console codepage/encoding mismatch
    assert "vpc-0abcdef" in status_response.json()["reasoning"]


def test_scenario_7_error_budget_gating():
    """Scenario 7: Error Budget Exhaustion (Containment features are hard-locked to ALERT_ONLY)."""
    # 1. Reset error budget first
    client.post(f"/v1/tenants/{tenant_id}/error-budget/reset")
    
    # 2. Simulate rollback to burn error budget
    audit_id_mock = "audit-f92a10b4-93e1-4560-bf87-9d7a22ef3f22"
    MOCK_DYNAMODB_AUDIT_STORE[audit_id_mock] = {
        "status": "COMPLETED",
        "audit_id": audit_id_mock,
        "anomaly": True,
        "suggested_action": "SCHEDULE_SHUTDOWN",
        "reasoning": "Original analysis reasoning."
    }
    client.post(
        f"/v1/audit/{audit_id_mock}/rollback",
        json={"operator": "user-dev-05", "rollback_ts": "2026-06-22T14:30:00Z", "reason_for_rollback": "false alarm"},
        headers={"X-Tenant-Id": tenant_id}
    )
    
    # Verify budget is burned (> 1% error rate)
    budget_res = client.get(f"/v1/tenants/{tenant_id}/error-budget")
    assert budget_res.json()["exhausted"] is True
    
    # 3. Request detect on an anomaly -> verify action is locked to ALERT_ONLY
    payload = get_base_payload(spend_value=450.0, idle_hours=18.0, cpu_util=3.0, env="dev")
    response = client.post(
        "/v1/detect", 
        json=payload, 
        headers={"X-Tenant-Id": tenant_id, "X-Idempotency-Key": "squad12_20260623_scen7"}
    )
    assert response.status_code == 202
    audit_id = response.json()["audit_id"]
    
    time.sleep(0.1)
    status_response = client.get(f"/v1/status/{audit_id}")
    assert status_response.status_code == 200
    assert status_response.json()["suggested_action"] == "ALERT_ONLY"
    # Use ASCII check to avoid Windows console codepage/encoding mismatch
    assert "SLO" in status_response.json()["reasoning"]
    
    # Cleanup
    client.post(f"/v1/tenants/{tenant_id}/error-budget/reset")


def test_scenario_8_insufficient_history():
    """Scenario 8: Insufficient Data Ingestion (Warm-up window check fails)."""
    # Send only 5 days of history (warm-up requires minimum 14)
    signals = []
    for i in range(1, 6):
        signals.append({
            "ts": f"2026-06-{i:02d}T00:00:00Z",
            "signal_name": "daily_cur_spend_usd",
            "value": 50.0
        })
    payload = {
        "signal_window": signals,
        "context": {
            "time_range": {"start_ts": "2026-06-01T00:00:00Z", "end_ts": "2026-06-05T00:00:00Z"}
        }
    }
    response = client.post(
        "/v1/detect", 
        json=payload, 
        headers={"X-Tenant-Id": tenant_id, "X-Idempotency-Key": "squad12_20260623_scen8"}
    )
    assert response.status_code == 202
    audit_id = response.json()["audit_id"]
    
    time.sleep(0.1)
    status_response = client.get(f"/v1/status/{audit_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "FAILED"
    # Use ASCII check to avoid Windows console codepage/encoding mismatch
    assert "Warm-up" in status_response.json()["reasoning"] or "Holt-Winters" in status_response.json()["reasoning"]


def test_scenario_9_idempotency():
    """Scenario 9: Idempotency protection (Second duplicate request returns cached response instantly)."""
    payload = get_base_payload(spend_value=450.0, idle_hours=18.0)
    key = "squad12_20260623_scen9"
    
    # First call
    response1 = client.post("/v1/detect", json=payload, headers={"X-Tenant-Id": tenant_id, "X-Idempotency-Key": key})
    assert response1.status_code == 202
    audit_id1 = response1.json()["audit_id"]
    
    # Second call (immediate)
    response2 = client.post("/v1/detect", json=payload, headers={"X-Tenant-Id": tenant_id, "X-Idempotency-Key": key})
    assert response2.status_code == 202
    # Should return the exact same audit_id from cache
    assert response2.json()["audit_id"] == audit_id1


def test_scenario_10_bedrock_outage():
    """Scenario 10: Bedrock outage (Triggers circuit breaker fallback using local stats/rules)."""
    payload = get_base_payload(spend_value=450.0, idle_hours=18.0)
    response = client.post(
        "/v1/detect", 
        json=payload, 
        headers={
            "X-Tenant-Id": tenant_id, 
            "X-Idempotency-Key": "squad12_20260623_scen10",
            "X-Simulate-Bedrock-Outage": "true"
        }
    )
    assert response.status_code == 202
    audit_id = response.json()["audit_id"]
    
    time.sleep(0.1)
    status_response = client.get(f"/v1/status/{audit_id}")
    assert status_response.status_code == 200
    assert status_response.json()["fallback_active"] is True
    assert "Circuit Breaker" in status_response.json()["reasoning"]


if __name__ == "__main__":
    print("==================================================")
    print("Running Rigorous 10-Scenario Test Suite...")
    print("==================================================")
    
    test_scenario_1_happy_path()
    print("Scenario 1 [Happy Path] ........................ PASSED")
    
    test_scenario_2_runaway_training_dev()
    print("Scenario 2 [Runaway Dev anomaly] ............... PASSED")
    
    test_scenario_3_prod_safety_guard()
    print("Scenario 3 [Production Safety Gating] .......... PASSED")
    
    test_scenario_4_whitelist_bypass()
    print("Scenario 4 [Core Whitelist Bypass] ............. PASSED")
    
    test_scenario_5_business_growth()
    print("Scenario 5 [High CPU Business Growth] .......... PASSED")
    
    test_scenario_6_fallback_spawning()
    print("Scenario 6 [Fallback Spatial Metadata] ......... PASSED")
    
    test_scenario_7_error_budget_gating()
    print("Scenario 7 [Error Budget Lockout] .............. PASSED")
    
    test_scenario_8_insufficient_history()
    print("Scenario 8 [Insufficent History check] ......... PASSED")
    
    test_scenario_9_idempotency()
    print("Scenario 9 [Idempotency Key Cache] ............. PASSED")
    
    test_scenario_10_bedrock_outage()
    print("Scenario 10 [Bedrock Outage Fallback] .......... PASSED")
    
    print("==================================================")
    print("SUCCESS: All 10 scenarios passed successfully!")
    print("==================================================")
