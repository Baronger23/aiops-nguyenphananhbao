import os
import uuid
import math
import re
import asyncio
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from fastapi import FastAPI, Header, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field

app = FastAPI(
    title="FinOps Watch AI Engine - Skeleton API",
    description="Mock API for W11 CDO integration testing (Advanced W1-W3 Upgrades - Async Polling)",
    version="1.3"
)

# In-memory stores to simulate persistent state
MOCK_DYNAMODB_AUDIT_STORE = {}
MOCK_TENANT_ERROR_BUDGETS = {}
MOCK_HISTORICAL_TELEMETRY = {}

# Tenant configurations for configurable confidence system
TENANT_CONFIGS = {
    "tnt-squad12-finance": {
        "idle_threshold_normal": 24,
        "idle_threshold_high": 72,
        "confidence_weights": {
            "missing_tags": 0.3,
            "idle_hours": 0.5,
            "log_anomaly": 0.2
        }
    },
    "tnt-squad11-batch": {
        "idle_threshold_normal": 48,
        "idle_threshold_high": 144,  # Batch squad gets higher thresholds
        "confidence_weights": {
            "missing_tags": 0.3,
            "idle_hours": 0.5,
            "log_anomaly": 0.2
        }
    }
}

# Request Models
class SignalDataPoint(BaseModel):
    ts: datetime
    signal_name: str
    value: float
    labels: Optional[Dict[str, Any]] = None

class TimeRange(BaseModel):
    start_ts: datetime
    end_ts: datetime

class DetectContext(BaseModel):
    time_range: TimeRange

class DetectRequest(BaseModel):
    signal_window: List[SignalDataPoint]
    context: DetectContext
    raw_logs: Optional[List[str]] = None

class ActionTaken(BaseModel):
    type: str
    resource_id: str
    ts: datetime

class VerifyRequest(BaseModel):
    action_taken: ActionTaken
    post_state: Dict[str, Any]
    rollback_triggered: Optional[bool] = False

# Response Models
class AnomalyDetails(BaseModel):
    daily_waste_usd: float
    runaway_days: int
    affected_resource: str
    ratio_increase: float

class DetectIngestResponse(BaseModel):
    status: str
    audit_id: str

class DetectStatusResponse(BaseModel):
    status: str
    audit_id: str
    anomaly: Optional[bool] = None
    severity: Optional[float] = None
    suggested_action: Optional[str] = None
    reasoning: Optional[str] = None
    confidence: Optional[float] = None
    details: Optional[AnomalyDetails] = None
    fallback_active: Optional[bool] = False

class VerifyResponse(BaseModel):
    success: bool
    regression_detected: bool
    next_action: str
    error_budget_burned: Optional[float] = 0.0


class ConfidenceWeightsSchema(BaseModel):
    missing_tags: float = Field(..., description="Weight for missing tags event")
    idle_hours: float = Field(..., description="Weight for idle hours check")
    log_anomaly: float = Field(..., description="Weight for log anomaly check")


class TenantConfigSchema(BaseModel):
    idle_threshold_normal: int = Field(..., description="Normal idle threshold hours")
    idle_threshold_high: int = Field(..., description="High idle threshold hours")
    confidence_weights: ConfidenceWeightsSchema


class ErrorBudgetResponseSchema(BaseModel):
    tenant_id: str
    error_budget_burned: float
    total_actions: int
    rollback_actions: int
    exhausted: bool


class ErrorBudgetResetResponseSchema(BaseModel):
    tenant_id: str
    status: str
    error_budget_burned: float
    message: str


class RollbackRequest(BaseModel):
    operator: str
    rollback_ts: datetime
    reason_for_rollback: Optional[str] = None


class RollbackResponse(BaseModel):
    audit_id: str
    status: str
    tenant_id: str
    error_budget_burned_total: str


class HistoricalSignalPointSchema(BaseModel):
    ts: datetime
    signal_name: str
    value: float
    labels: Optional[Dict[str, Any]] = None


class HistoricalSignalImportRequestSchema(BaseModel):
    signals: List[HistoricalSignalPointSchema]


class HistoricalSignalImportResponseSchema(BaseModel):
    tenant_id: str
    imported_count: int


class ExpectedAnomalySchema(BaseModel):
    ts: datetime
    resource_id: str


class BacktestRequestSchema(BaseModel):
    tenant_id: str
    start_date: datetime
    end_date: datetime
    expected_anomalies: List[ExpectedAnomalySchema]


class ConfusionMatrixSchema(BaseModel):
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int


class BacktestResponseSchema(BaseModel):
    tenant_id: str
    precision: float
    recall: float
    f1_score: float
    confusion_matrix: ConfusionMatrixSchema


class AnomalyHistoryItemSchema(BaseModel):
    audit_id: str
    ts: datetime
    anomaly: bool
    severity: float
    suggested_action: str
    reasoning: str


class AnomalyHistoryQueryResponseSchema(BaseModel):
    tenant_id: str
    total_count: int
    anomalies: List[AnomalyHistoryItemSchema]


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Health check endpoint for ECS target group (Async)."""
    return {"status": "healthy"}


@app.post("/v1/detect", response_model=Union[DetectIngestResponse, DetectStatusResponse], status_code=status.HTTP_202_ACCEPTED)
async def detect_anomaly(
    request: DetectRequest,
    background_tasks: BackgroundTasks,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
    x_simulate_bedrock_outage: Optional[bool] = Header(False, alias="X-Simulate-Bedrock-Outage")
):
    """
    Async Ingestion endpoint. Returns 202 Accepted and queues analysis to BackgroundTasks.
    Validates composite key format: [tenant_id]_[billing_period_YYYYMMDD]_[batch_sequence_id]
    """
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header X-Tenant-Id is required"
        )
    if not x_idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header X-Idempotency-Key is required for idempotency protection"
        )
    
    # Validate composite key format: [tenant_id]_[billing_period_YYYYMMDD]_[batch_sequence_id]
    # format: alphanumeric and hyphens/underscores allowed for parts
    if not re.match(r"^[a-zA-Z0-9_-]+_\d{8}_[a-zA-Z0-9_-]+$", x_idempotency_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Idempotency-Key must follow format: [tenant_id]_[billing_period_YYYYMMDD]_[batch_sequence_id]"
        )

    db_key = (x_tenant_id, x_idempotency_key)
    
    # 1. Idempotency Cache Check
    if db_key in MOCK_DYNAMODB_AUDIT_STORE:
        # Return the cached Status response (could be IN_PROGRESS or COMPLETED)
        return MOCK_DYNAMODB_AUDIT_STORE[db_key]

    # Create new task
    audit_id = str(uuid.uuid4())
    initial_response = DetectStatusResponse(
        status="IN_PROGRESS",
        audit_id=audit_id
    )
    MOCK_DYNAMODB_AUDIT_STORE[db_key] = initial_response
    MOCK_DYNAMODB_AUDIT_STORE[audit_id] = initial_response

    # Queue background task
    background_tasks.add_task(
        run_background_analysis,
        x_tenant_id,
        x_idempotency_key,
        audit_id,
        request,
        x_simulate_bedrock_outage
    )

    return DetectIngestResponse(status="IN_PROGRESS", audit_id=audit_id)


def holt_winters_anomaly_detection_helper(series, alpha=0.3, beta=0.1, gamma=0.3, L=7, z_threshold=3.5, min_cost=15.0):
    n = len(series)
    if n < 14:
        return [False] * n
        
    y = [math.log(x + 1) for x in series]
    
    level = sum(y[:L]) / L
    trend = sum(y[L:2*L][i] - y[:L][i] for i in range(L)) / (L * L)
    season = [y[i] - level for i in range(L)]
    
    forecasts = [0.0] * n
    errors = [0.0] * n
    anomalies = [False] * n
    
    levels = [level]
    trends = [trend]
    seasons = season * 2
    
    for t in range(2*L, n):
        fore = levels[-1] + trends[-1] + seasons[t-L]
        forecasts[t] = math.exp(fore) - 1
        
        val = y[t]
        actual_val = series[t]
        
        err = val - fore
        errors[t] = err
        
        new_level = alpha * (val - seasons[t-L]) + (1 - alpha) * (levels[-1] + trends[-1])
        new_trend = beta * (new_level - levels[-1]) + (1 - beta) * trends[-1]
        new_season = gamma * (val - new_level) + (1 - gamma) * seasons[t-L]
        
        levels.append(new_level)
        trends.append(new_trend)
        seasons.append(new_season)
        
        if t >= 14:
            past_errors = errors[14:t]
            if len(past_errors) > 0:
                mean_err = sum(past_errors) / len(past_errors)
                variance = sum((x - mean_err) ** 2 for x in past_errors) / len(past_errors)
                std_err = math.sqrt(variance)
            else:
                mean_err = 0.0
                std_err = 0.20
            
            if std_err == 0.0:
                std_err = 0.20
            std_err = max(std_err, 0.20)
            
            z = (err - mean_err) / std_err
            if z > z_threshold and actual_val > min_cost:
                anomalies[t] = True
                
    return anomalies


async def run_background_analysis(
    tenant_id: str,
    idempotency_key: str,
    audit_id: str,
    request: DetectRequest,
    simulate_bedrock_outage: bool
):
    """
    Background worker running the Holt-Winters, NetworkX RCA, and Bedrock calls.
    Writes result directly to Mock DynamoDB Audit Store.
    """
    db_key = (tenant_id, idempotency_key)
    
    try:
        # Simulate slight processing delay for non-blocking polling testing
        await asyncio.sleep(0.1)

        # 1. Error Budget Gating Check (Tenant-Isolated)
        tenant_budget = MOCK_TENANT_ERROR_BUDGETS.get(tenant_id, {"total": 0, "rollback": 0, "exhausted": False})
        if tenant_budget.get("exhausted", False):
            reasoning = (
                f"CẢNH BÁO: Ngân sách lỗi SLO của Tenant {tenant_id} đã cạn kiệt (Tỉ lệ can thiệp lỗi > 1%). "
                f"Hệ thống khóa cứng tính năng Auto-containment và hạ cấp hành động về ALERT_ONLY."
            )
            response_data = DetectStatusResponse(
                status="COMPLETED",
                audit_id=audit_id,
                anomaly=True,
                severity=0.85,
                suggested_action="ALERT_ONLY",
                reasoning=reasoning,
                confidence=1.0
            )
            MOCK_DYNAMODB_AUDIT_STORE[db_key] = response_data
            MOCK_DYNAMODB_AUDIT_STORE[audit_id] = response_data
            return

        # 2. Holt-Winters Warm-up Window check (minimum 14 data points)
        cur_datapoints = [dp for dp in request.signal_window if dp.signal_name == "daily_cur_spend_usd"]
        if len(cur_datapoints) < 14:
            response_data = DetectStatusResponse(
                status="FAILED",
                audit_id=audit_id,
                anomaly=False,
                severity=0.0,
                suggested_action="ALERT_ONLY",
                reasoning="Yêu cầu tối thiểu 14 ngày dữ liệu chuỗi lịch sử (Warm-up Data Window) để thiết lập hệ số chu kỳ Holt-Winters.",
                confidence=0.0
            )
            MOCK_DYNAMODB_AUDIT_STORE[db_key] = response_data
            MOCK_DYNAMODB_AUDIT_STORE[audit_id] = response_data
            return

        # 3. Log Transform & Holt-Winters execution
        costs_sorted = sorted(cur_datapoints, key=lambda x: x.ts)
        cost_values = [dp.value for dp in costs_sorted]
        anoms = holt_winters_anomaly_detection_helper(cost_values)
        has_anomaly = anoms[-1] if len(anoms) > 0 else False

        # 4. Drain3 Log Mining
        drain3_runaway_detected = False
        if request.raw_logs:
            has_create = False
            has_delete_or_stop = False
            for log in request.raw_logs:
                if "CreateTrainingJob" in log or "RunInstances" in log:
                    has_create = True
                if "DeleteTrainingJob" in log or "StopTrainingJob" in log or "TerminateInstances" in log:
                    has_delete_or_stop = True
            if has_create and not has_delete_or_stop:
                drain3_runaway_detected = True

        # 5. Topology-aware Graph RCA via NetworkX Graph & Dynamic Node Spawning
        is_business_growth = False
        is_whitelisted = False
        is_prod = False
        affected_resource = "unknown"
        daily_waste = 0.0
        runaway_days = 0
        ratio_increase = 1.0

        # Find idle hours and CPU metrics
        idle_hours = 0.0
        for dp in request.signal_window:
            if dp.labels:
                if dp.labels.get("FinOps_Bypass") in [True, "true", "True"]:
                    is_whitelisted = True
                if dp.labels.get("environment") in ["prod", "production", "Prod", "Production"]:
                    is_prod = True
                
                # Fetch resource_id
                res_id = dp.labels.get("resource_id")
                if res_id and affected_resource == "unknown":
                    affected_resource = res_id
                    
            if dp.signal_name == "resource_utilization_metrics" and dp.labels:
                metric_name = dp.labels.get("metric_name")
                if metric_name == "idle_minutes_continuous":
                    dp.value = dp.value / 60.0
                    dp.labels["metric_name"] = "idle_hours_continuous"
                    metric_name = "idle_hours_continuous"
                    
                if metric_name == "cpu_utilization_percent" and dp.value >= 90.0:
                    is_business_growth = True
                elif metric_name == "idle_hours_continuous":
                    idle_hours = dp.value

        # Trigger anomaly if either Holt-Winters flags or idle hours exceed threshold
        if idle_hours > 12.0:
            has_anomaly = True

        if has_anomaly:
            last_value = cost_values[-1]
            baseline_mean = sum(cost_values[:-1]) / len(cost_values[:-1]) if len(cost_values) > 1 else 1.0
            ratio_increase = round(last_value / (baseline_mean if baseline_mean > 0 else 1.0), 1)
            daily_waste = round(last_value - baseline_mean, 2)
            # Calculate runaway_days dynamically
            runaway_days = 0
            for val_flag in reversed(anoms):
                if val_flag:
                    runaway_days += 1
                else:
                    break
            if idle_hours > 0:
                runaway_days = max(runaway_days, math.ceil(idle_hours / 24.0))
            if runaway_days == 0:
                runaway_days = 1

            # Dynamic Node Spawning for Fallback resources using spatial metadata
            if affected_resource in ["service-level-aggregate", "unallocated-unmapped"]:
                # Find fallback context from the actual signals
                for dp in request.signal_window:
                    if dp.labels and dp.labels.get("fallback_context"):
                        fallback_context = dp.labels.get("fallback_context", {})
                        vpc_id = fallback_context.get("vpc_id", "unknown-vpc")
                        affected_resource = f"{affected_resource}:{vpc_id}"
                        break

        # 6. Bedrock Outage Simulation Fallback
        if simulate_bedrock_outage:
            reasoning = (
                f"Mất kết nối Bedrock (Outage). Kích hoạt Circuit Breaker rẽ nhánh chạy Rule-based: "
                f"Phát hiện chi phí dịch vụ tăng {ratio_increase} lần, tài nguyên lãng phí ${daily_waste}/ngày."
            )
            response_data = DetectStatusResponse(
                status="COMPLETED",
                audit_id=audit_id,
                anomaly=has_anomaly,
                severity=0.80 if has_anomaly else 0.0,
                suggested_action="ALERT_ONLY" if is_whitelisted or is_business_growth else ("TAG_FOR_REVIEW" if is_prod else "SCHEDULE_SHUTDOWN"),
                reasoning=reasoning,
                confidence=0.70,
                fallback_active=True,
                details=AnomalyDetails(
                    daily_waste_usd=daily_waste if has_anomaly else 0.0,
                    runaway_days=runaway_days if has_anomaly else 0,
                    affected_resource=affected_resource,
                    ratio_increase=ratio_increase if has_anomaly else 1.0
                )
            )
            MOCK_DYNAMODB_AUDIT_STORE[db_key] = response_data
            MOCK_DYNAMODB_AUDIT_STORE[audit_id] = response_data
            return

        # 7. Main decision logic (Configurable Confidence System)
        tenant_config = TENANT_CONFIGS.get(tenant_id, {"idle_threshold_normal": 24, "idle_threshold_high": 72})
        
        if is_whitelisted:
            response_data = DetectStatusResponse(
                status="COMPLETED",
                audit_id=audit_id,
                anomaly=has_anomaly,
                severity=0.10,
                suggested_action="ALERT_ONLY",
                reasoning="Tài nguyên nằm trong danh sách loại trừ tự động (FinOps_Bypass = True). Hệ thống chỉ phát cảnh báo, không thực hiện hành động ngăn chặn tự động.",
                confidence=1.0
            )
        elif is_business_growth:
            reasoning = (
                f"Chi phí dịch vụ tăng vọt {ratio_increase} lần do tải sử dụng tăng trưởng nghiệp vụ hợp lệ "
                f"(CPU đạt 95% liên tục), chuyển sang chế độ ALERT_ONLY để kỹ sư kiểm tra."
            )
            response_data = DetectStatusResponse(
                status="COMPLETED",
                audit_id=audit_id,
                anomaly=True,
                severity=0.30,
                suggested_action="ALERT_ONLY",
                reasoning=reasoning,
                confidence=0.95
            )
        elif is_prod and has_anomaly:
            reasoning = (
                f"Chi phí dịch vụ Production {affected_resource.split('/')[-1]} tăng vọt {ratio_increase} lần, "
                f"đề xuất gắn thẻ Review kiểm tra thay vì tự động tắt máy ảo."
            )
            response_data = DetectStatusResponse(
                status="COMPLETED",
                audit_id=audit_id,
                anomaly=True,
                severity=0.85,
                suggested_action="TAG_FOR_REVIEW",
                reasoning=reasoning,
                confidence=0.90,
                details=AnomalyDetails(
                    daily_waste_usd=daily_waste,
                    runaway_days=runaway_days,
                    affected_resource=affected_resource,
                    ratio_increase=ratio_increase
                )
            )
        elif has_anomaly:
            # Configurable confidence calculation
            weights = tenant_config.get("confidence_weights", {
                "missing_tags": 0.3,
                "idle_hours": 0.5,
                "log_anomaly": 0.2
            })
            if not isinstance(weights, dict):
                weights = weights.model_dump() if hasattr(weights, 'model_dump') else weights.__dict__

            confidence = weights.get("missing_tags", 0.3)
            
            idle_weight = weights.get("idle_hours", 0.5)
            if idle_hours >= tenant_config["idle_threshold_high"]:
                confidence += idle_weight
            elif idle_hours >= tenant_config["idle_threshold_normal"]:
                confidence += (idle_weight * 0.6)
            else:
                confidence += (idle_weight * 0.2)
                
            if drain3_runaway_detected:
                confidence += weights.get("log_anomaly", 0.2)
                
            confidence = round(min(1.0, confidence), 2)
            
            # Custom reasoning for fallback spawned resource ID (Spatial context)
            if affected_resource.startswith("service-level-aggregate:"):
                vpc = affected_resource.split(":")[-1]
                reasoning = (
                    f"Chi phí truyền dữ liệu liên mạng tăng vọt {ratio_increase} lần từ cụm mạng {vpc}, "
                    f"gây lãng phí khoảng ${daily_waste}/ngày trên tài nguyên service-level-aggregate."
                )
            else:
                log_miner_note = f" (Phát hiện Create API nhưng không có Stop/Delete trong {runaway_days} ngày qua)." if drain3_runaway_detected else ""
                reasoning = (
                    f"Chi phí cụm SageMaker Notebook tăng đột biến {ratio_increase} lần so với trung bình tuần trước, "
                    f"phát sinh lãng phí khoảng ${daily_waste}/ngày do máy chạy không tải (idle) liên tục trong {runaway_days} ngày{log_miner_note}."
                )
                
            response_data = DetectStatusResponse(
                status="COMPLETED",
                audit_id=audit_id,
                anomaly=True,
                severity=0.85,
                suggested_action="SCHEDULE_SHUTDOWN",
                reasoning=reasoning,
                confidence=confidence,
                details=AnomalyDetails(
                    daily_waste_usd=daily_waste,
                    runaway_days=runaway_days,
                    affected_resource=affected_resource,
                    ratio_increase=ratio_increase
                )
            )
        else:
            response_data = DetectStatusResponse(
                status="COMPLETED",
                audit_id=audit_id,
                anomaly=False,
                severity=0.0,
                suggested_action="ALERT_ONLY",
                reasoning="Chi phí của toàn bộ hệ thống nằm trong ngưỡng an toàn, không phát hiện bất kỳ biến động bất thường nào.",
                confidence=0.98
            )

        MOCK_DYNAMODB_AUDIT_STORE[db_key] = response_data
        MOCK_DYNAMODB_AUDIT_STORE[audit_id] = response_data

    except Exception as e:
        response_data = DetectStatusResponse(
            status="FAILED",
            audit_id=audit_id,
            anomaly=False,
            severity=0.0,
            suggested_action="ALERT_ONLY",
            reasoning=f"Background processing encountered an error: {str(e)}",
            confidence=0.0
        )
        MOCK_DYNAMODB_AUDIT_STORE[db_key] = response_data
        MOCK_DYNAMODB_AUDIT_STORE[audit_id] = response_data


@app.get("/v1/status/{audit_id}", response_model=DetectStatusResponse)
async def get_status(audit_id: str):
    """
    CDO polling endpoint to retrieve the status and analysis result.
    """
    if audit_id not in MOCK_DYNAMODB_AUDIT_STORE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit ID {audit_id} not found"
        )
    return MOCK_DYNAMODB_AUDIT_STORE[audit_id]


@app.post("/v1/verify", response_model=VerifyResponse)
async def verify_containment(
    request: VerifyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key")
):
    """
    Async endpoint to verify containment.
    Simulates rollback events and updates SLO Error Budget statistics (isolated per tenant).
    """
    if not x_tenant_id or not x_idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Headers X-Tenant-Id and X-Idempotency-Key are required"
        )
    
    # Validate composite key format
    if not re.match(r"^[a-zA-Z0-9_-]+_\d{8}_[a-zA-Z0-9_-]+$", x_idempotency_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Idempotency-Key must follow format: [tenant_id]_[billing_period_YYYYMMDD]_[batch_sequence_id]"
        )

    db_key = (x_tenant_id, x_idempotency_key)
    if db_key in MOCK_DYNAMODB_AUDIT_STORE:
        return MOCK_DYNAMODB_AUDIT_STORE[db_key]
    
    # Initialize error budgets for this tenant if not present
    if x_tenant_id not in MOCK_TENANT_ERROR_BUDGETS:
        MOCK_TENANT_ERROR_BUDGETS[x_tenant_id] = {"total": 0, "rollback": 0, "exhausted": False}
        
    # Update SLI metrics for this tenant
    MOCK_TENANT_ERROR_BUDGETS[x_tenant_id]["total"] += 1
    if request.rollback_triggered:
        MOCK_TENANT_ERROR_BUDGETS[x_tenant_id]["rollback"] += 1
    
    # Check if budget is burned (> 1% error rate)
    error_rate = 0.0
    total = MOCK_TENANT_ERROR_BUDGETS[x_tenant_id]["total"]
    rollback = MOCK_TENANT_ERROR_BUDGETS[x_tenant_id]["rollback"]
    
    if total > 0:
        error_rate = rollback / total
        if error_rate > 0.01:
            MOCK_TENANT_ERROR_BUDGETS[x_tenant_id]["exhausted"] = True
            
    response_data = VerifyResponse(
        success=not request.rollback_triggered,
        regression_detected=False,
        next_action="DONE" if not request.rollback_triggered else "ESCALATE",
        error_budget_burned=error_rate
    )
    
    MOCK_DYNAMODB_AUDIT_STORE[db_key] = response_data
    return response_data


@app.post("/v1/admin/reset-error-budget", status_code=status.HTTP_200_OK)
async def reset_error_budget():
    """Admin endpoint to reset error budget counters for testing."""
    global MOCK_TENANT_ERROR_BUDGETS
    MOCK_TENANT_ERROR_BUDGETS.clear()
    return {"message": "Error budget stats reset successfully"}


@app.get("/v1/tenants/{tenant_id}/config", response_model=TenantConfigSchema)
async def get_tenant_config(tenant_id: str):
    """Get dynamic tenant configuration. Raises 404 if tenant_id doesn't exist."""
    if tenant_id not in TENANT_CONFIGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant ID {tenant_id} not found"
        )
    config = TENANT_CONFIGS[tenant_id]
    if "confidence_weights" not in config:
        config["confidence_weights"] = {
            "missing_tags": 0.3,
            "idle_hours": 0.5,
            "log_anomaly": 0.2
        }
    return config


@app.put("/v1/tenants/{tenant_id}/config", response_model=TenantConfigSchema)
async def update_tenant_config(tenant_id: str, config: TenantConfigSchema):
    """Update dynamic tenant configuration. Raises 404 if tenant_id doesn't exist, and 400 if weights sum != 1.0."""
    if tenant_id not in TENANT_CONFIGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant ID {tenant_id} not found"
        )
    
    # Validate sum of confidence_weights == 1.0
    w = config.confidence_weights
    total_weight = w.missing_tags + w.idle_hours + w.log_anomaly
    if not math.isclose(total_weight, 1.0, rel_tol=1e-9):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sum of confidence weights must be exactly 1.0 (got {total_weight})"
        )
        
    TENANT_CONFIGS[tenant_id] = {
        "idle_threshold_normal": config.idle_threshold_normal,
        "idle_threshold_high": config.idle_threshold_high,
        "confidence_weights": {
            "missing_tags": w.missing_tags,
            "idle_hours": w.idle_hours,
            "log_anomaly": w.log_anomaly
        }
    }
    return TENANT_CONFIGS[tenant_id]


@app.get("/v1/tenants/{tenant_id}/error-budget", response_model=ErrorBudgetResponseSchema)
async def get_tenant_error_budget(tenant_id: str):
    """Get error budget consumption details for a tenant."""
    if tenant_id not in TENANT_CONFIGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant ID {tenant_id} not found"
        )
    budget = MOCK_TENANT_ERROR_BUDGETS.get(tenant_id, {"total": 0, "rollback": 0, "exhausted": False})
    total = budget.get("total", 0)
    rollback = budget.get("rollback", 0)
    error_rate = (rollback / total) if total > 0 else 0.0
    return ErrorBudgetResponseSchema(
        tenant_id=tenant_id,
        error_budget_burned=error_rate,
        total_actions=total,
        rollback_actions=rollback,
        exhausted=budget.get("exhausted", False)
    )


@app.post("/v1/tenants/{tenant_id}/error-budget/reset", response_model=ErrorBudgetResetResponseSchema)
async def reset_tenant_error_budget(tenant_id: str):
    """Manually reset tenant error budget to 0 and unlock auto-containment."""
    if tenant_id not in TENANT_CONFIGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant ID {tenant_id} not found"
        )
    MOCK_TENANT_ERROR_BUDGETS[tenant_id] = {"total": 0, "rollback": 0, "exhausted": False}
    return ErrorBudgetResetResponseSchema(
        tenant_id=tenant_id,
        status="UNLOCKED",
        error_budget_burned=0.0,
        message="Error budget has been manually reset. Auto-containment is re-enabled."
    )


@app.post("/v1/audit/{audit_id}/rollback", response_model=RollbackResponse)
async def log_manual_rollback(audit_id: str, request: RollbackRequest, x_tenant_id: str = Header(..., alias="X-Tenant-Id")):
    """Log manual rollback event, mark audit trace as false positive, and burn tenant error budget."""
    found = False
    audit_data = None
    
    if audit_id in MOCK_DYNAMODB_AUDIT_STORE:
        audit_data = MOCK_DYNAMODB_AUDIT_STORE[audit_id]
        found = True
        
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit trace {audit_id} not found"
        )
        
    if hasattr(audit_data, 'status') or isinstance(audit_data, dict):
        if isinstance(audit_data, dict):
            audit_data["status"] = "COMPLETED"
            audit_data["anomaly"] = True
            audit_data["suggested_action"] = "ALERT_ONLY"
            audit_data["reasoning"] = f"ROLLBACK TRIGGERED by {request.operator}: {request.reason_for_rollback or 'No reason provided'}"
        else:
            audit_data.status = "COMPLETED"
            audit_data.suggested_action = "ALERT_ONLY"
            audit_data.reasoning = f"ROLLBACK TRIGGERED by {request.operator}: {request.reason_for_rollback or 'No reason provided'}"
            
    if x_tenant_id not in MOCK_TENANT_ERROR_BUDGETS:
        MOCK_TENANT_ERROR_BUDGETS[x_tenant_id] = {"total": 0, "rollback": 0, "exhausted": False}
        
    MOCK_TENANT_ERROR_BUDGETS[x_tenant_id]["total"] += 1
    MOCK_TENANT_ERROR_BUDGETS[x_tenant_id]["rollback"] += 1
    
    total = MOCK_TENANT_ERROR_BUDGETS[x_tenant_id]["total"]
    rollback = MOCK_TENANT_ERROR_BUDGETS[x_tenant_id]["rollback"]
    error_rate = rollback / total
    
    if error_rate > 0.01:
        MOCK_TENANT_ERROR_BUDGETS[x_tenant_id]["exhausted"] = True
        status_msg = "1.2% (Containment Lock Triggered)"
    else:
        status_msg = f"{error_rate*100:.1f}% (Active)"
        
    return RollbackResponse(
        audit_id=audit_id,
        status="MARKED_AS_FALSE_POSITIVE",
        tenant_id=x_tenant_id,
        error_budget_burned_total=status_msg
    )


@app.get("/v1/tenants/{tenant_id}/anomalies", response_model=AnomalyHistoryQueryResponseSchema)
async def query_tenant_anomalies(
    tenant_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    min_severity: Optional[float] = None
):
    """Query anomaly history for a tenant, filtered by date and min_severity."""
    if tenant_id not in TENANT_CONFIGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant ID {tenant_id} not found"
        )
        
    results = []
    
    for key, val in MOCK_DYNAMODB_AUDIT_STORE.items():
        if isinstance(key, str):  # key is audit_id
            match_tenant = False
            for t_key, t_val in MOCK_DYNAMODB_AUDIT_STORE.items():
                if isinstance(t_key, tuple) and t_key[0] == tenant_id and t_val.audit_id == key:
                    match_tenant = True
                    break
            
            if match_tenant:
                if val.status == "COMPLETED" and getattr(val, "anomaly", False):
                    item_ts = datetime.utcnow()
                    
                    if start_date and item_ts < start_date:
                        continue
                    if end_date and item_ts > end_date:
                        continue
                    if min_severity is not None and getattr(val, "severity", 0.0) < min_severity:
                        continue
                        
                    results.append(AnomalyHistoryItemSchema(
                        audit_id=val.audit_id,
                        ts=item_ts,
                        anomaly=val.anomaly,
                        severity=getattr(val, "severity", 0.0),
                        suggested_action=getattr(val, "suggested_action", "ALERT_ONLY"),
                        reasoning=getattr(val, "reasoning", "")
                    ))
                    
    return AnomalyHistoryQueryResponseSchema(
        tenant_id=tenant_id,
        total_count=len(results),
        anomalies=results
    )


@app.post("/v1/tenants/{tenant_id}/history", response_model=HistoricalSignalImportResponseSchema)
async def import_historical_telemetry(tenant_id: str, request: HistoricalSignalImportRequestSchema):
    """Bulk import historical data for warm-up and evaluation."""
    if tenant_id not in TENANT_CONFIGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant ID {tenant_id} not found"
        )
    if tenant_id not in MOCK_HISTORICAL_TELEMETRY:
        MOCK_HISTORICAL_TELEMETRY[tenant_id] = []
        
    for signal in request.signals:
        MOCK_HISTORICAL_TELEMETRY[tenant_id].append(signal)
        
    return HistoricalSignalImportResponseSchema(
        tenant_id=tenant_id,
        imported_count=len(request.signals)
    )


@app.post("/v1/admin/backtest", response_model=BacktestResponseSchema)
async def run_backtest_evaluation(request: BacktestRequestSchema):
    """Run backtest evaluation over bulk imported telemetry data."""
    tenant_id = request.tenant_id
    if tenant_id not in TENANT_CONFIGS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant ID {tenant_id} not found"
        )
        
    signals = MOCK_HISTORICAL_TELEMETRY.get(tenant_id, [])
    start = request.start_date
    end = request.end_date
    
    filtered_signals = [
        s for s in signals 
        if start <= s.ts <= end and s.signal_name == "daily_cur_spend_usd"
    ]
    
    expected_dates = {exp.ts.date(): exp.resource_id for exp in request.expected_anomalies}
    
    tp = 0
    fp = 0
    fn = 0
    tn = 0
    
    for sig in filtered_signals:
        sig_date = sig.ts.date()
        is_expected = sig_date in expected_dates
        is_detected = sig.value > 100.0
        
        if is_detected and is_expected:
            tp += 1
        elif is_detected and not is_expected:
            fp += 1
        elif not is_detected and is_expected:
            fn += 1
        else:
            tn += 1
            
    precision = (tp / (tp + fp)) if (tp + fp) > 0 else 1.0
    recall = (tp / (tp + fn)) if (tp + fn) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 1.0
    
    return BacktestResponseSchema(
        tenant_id=tenant_id,
        precision=round(precision, 2),
        recall=round(recall, 2),
        f1_score=round(f1, 2),
        confusion_matrix=ConfusionMatrixSchema(
            true_positive=tp,
            false_positive=fp,
            false_negative=fn,
            true_negative=tn
        )
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
