# AI API Contract - Task Force 2 (FinOps Watch)

<!-- Owner: Nhóm AI
     Signed by: AI Lead + CDO Leads × 2-3 + Reviewer panel
     Date signed: 2026-06-25 (W11 T5)
     🔒 FREEZE - no change without formal change request -->

## Mục đích

Định nghĩa **các API endpoints** mà Nhóm AI cung cấp cho Nhóm CDO để tích hợp hệ thống phát hiện bất thường và ra quyết định ngăn chặn chi phí (FinOps Watch).

## Versioning

- **Current version**: `v1.0` (trong đường dẫn `/v1/`)
- **Breaking changes** -> phiên bản `/v2/`, hỗ trợ song song tối thiểu 30 ngày.

## Authentication

- **Inter-service**: AWS IAM SigV4
- **Audit**: Lưu nhật ký kiểm toán cho toàn bộ sự kiện xác thực thành công/thất bại.

## Rate limiting & Idempotency

- **Per tenant**: Tối đa 60 requests/minute (áp dụng qua API Gateway usage plan).
- **Response on hit**: `429 Too Many Requests` kèm header `Retry-After: <seconds>`.
- **Cơ chế Idempotency (Khống chế Double-Run)**: 
  *   CDO bắt buộc phải đính kèm Header `X-Idempotency-Key` trên mọi request gửi tới endpoints `/v1/detect` và `/v1/verify`.
  *   **Định dạng bắt buộc (Time-bounded Composite Key)**: `[tenant_id]_[billing_period_YYYYMMDD]_[batch_sequence_id]` (ví dụ: `squad12_20260622_run01`). Nếu không đúng định dạng này, hệ thống sẽ trả về lỗi `400 Bad Request`. Việc ép đính kèm ngày chạy đảm bảo triệt tiêu hoàn toàn thảm họa cache đè dữ liệu lịch sử nếu CDO bị lỗi logic lặp.
  *   **Thiết lập TTL (Time-To-Live)**: Các bản ghi Idempotency lưu trong DynamoDB được cấu hình TTL là **24 giờ**. Sau 24 giờ, khóa tự động hết hiệu lực (expired) và bị xóa để giải phóng dung lượng, sẵn sàng cho chu kỳ batch tiếp theo.
  *   Nếu AI Engine phát hiện khóa `X-Idempotency-Key` đã tồn tại trong DynamoDB Audit Store cho cùng một `X-Tenant-Id`, AI Engine sẽ dừng ngay việc phân tích và trả về kết quả đã lưu trong bộ nhớ đệm (Cached Response).

---

## Endpoint 1: `POST /v1/detect`

**Mục đích**: Nhận yêu cầu phân tích chuỗi dữ liệu chi phí và tài nguyên (telemetry signals) trong 24h từ CDO. API hoạt động theo mô hình **Bất đồng bộ (Async Ingestion)**: Tiếp nhận request, đẩy mảng tín hiệu vào hàng đợi xử lý ngầm (Background Task) và lập tức trả về phản hồi kèm theo mã `audit_id` để CDO thực hiện polling.

### Request headers

| Header | Type | Required | Description |
|---|---|---|---|
| `X-Tenant-Id` | String | ✓ | Định danh tenant / squad chịu trách nhiệm chi phí |
| `X-Idempotency-Key` | String | ✓ | Khóa phân biệt giao dịch (định dạng composite) |
| `Authorization` | IAM SigV4 | ✓ | Xác thực liên dịch vụ |
| `X-Correlation-Id` | UUID | optional | Trace ID để theo dõi luồng |

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `signal_window` | array | ✓ | Chuỗi dữ liệu các tín hiệu (CUR spend, CPU, Tag) |
| `signal_window[].ts` | RFC3339 | ✓ | Thời điểm ghi nhận tín hiệu (UTC) |
| `signal_window[].signal_name` | string | ✓ | Tên tín hiệu (khớp với Telemetry Contract) |
| `signal_window[].value` | float | ✓ | Giá trị đo lường |
| `signal_window[].labels` | object | optional | Nhãn ngữ cảnh (service, environment, resource_id...) |
| `context.time_range.start_ts` | RFC3339 | ✓ | Thời gian bắt đầu cửa sổ phân tích |
| `context.time_range.end_ts` | RFC3339 | ✓ | Thời gian kết thúc cửa sổ phân tích |

**Request example**:

```json
{
  "signal_window": [
    {
      "ts": "2026-06-22T00:00:00Z",
      "signal_name": "daily_cur_spend_usd",
      "value": 420.00,
      "labels": {
        "resource_id": "arn:aws:sagemaker:ap-southeast-1:123456789012:notebook-instance/notebook-instance-training-v2",
        "service": "SageMaker",
        "squad_owner": "squad-prediction",
        "environment": "dev"
      }
    },
    {
      "ts": "2026-06-22T00:00:00Z",
      "signal_name": "resource_utilization_metrics",
      "value": 24.0,
      "labels": {
        "resource_id": "notebook-instance-training-v2",
        "resource_type": "SageMaker-Notebook",
        "metric_name": "idle_hours_continuous"
      }
    }
  ],
  "context": {
    "time_range": {
      "start_ts": "2026-06-21T00:00:00Z",
      "end_ts": "2026-06-22T00:00:00Z"
    }
  }
}
```

### Response body

Trả về mã trạng thái `202 Accepted` ngay lập tức (<50ms).

| Field | Type | Description |
|---|---|---|
| `status` | string | Trạng thái tiếp nhận: `"IN_PROGRESS"` |
| `audit_id` | UUID | Khóa định danh phiên giao dịch để CDO polling trạng thái |

**Response example**:

```json
{
  "status": "IN_PROGRESS",
  "audit_id": "audit-f92a10b4-93e1-4560-bf87-9d7a22ef3f22"
}
```

### SLA

| Metric | Target |
|---|---|
| **P99 latency** | < 50 ms (cho việc tiếp nhận và đẩy vào Background Task) |
| **Throughput** | 100 requests / minute |
| **Availability** | 99.5% |

---

## Endpoint 2: `GET /v1/status/{audit_id}`

**Mục đích**: CDO Platform gọi endpoint này sau mỗi 2-3 giây (Polling) để kiểm tra trạng thái và lấy kết quả phân tích bất thường chi phí từ DynamoDB Audit Store.

### Request headers

| Header | Type | Required | Description |
|---|---|---|---|
| `Authorization` | IAM SigV4 | ✓ | Xác thực liên dịch vụ |

### Response body

Trả về mã trạng thái `200 OK`.

| Field | Type | Description |
|---|---|---|
| `status` | string | Trạng thái xử lý: `"IN_PROGRESS"`, `"COMPLETED"`, `"FAILED"` |
| `audit_id` | UUID | Khóa định danh phiên giao dịch |
| `anomaly` | bool | `true` nếu phát hiện bất thường chi phí, `false` nếu bình thường (chỉ xuất hiện khi status: `"COMPLETED"`) |
| `severity` | float | Mức độ nghiêm trọng của bất thường (chỉ xuất hiện khi status: `"COMPLETED"`) |
| `suggested_action` | enum | Đề xuất hành động: `TAG_FOR_REVIEW`, `QUOTA_CAP`, `SCHEDULE_SHUTDOWN`, `ALERT_ONLY` (chỉ xuất hiện khi status: `"COMPLETED"`) |
| `reasoning` | string | Giải trình bằng ngôn ngữ tài chính Finance-friendly (chỉ xuất hiện khi status: `"COMPLETED"`) |
| `confidence` | float | Điểm tin cậy (chỉ xuất hiện khi status: `"COMPLETED"`) |
| `details` | object | Chi tiết lãng phí kinh tế (chỉ xuất hiện khi status: `"COMPLETED"`) |

> [!IMPORTANT]
> **Quy định nghiêm ngặt về trường giải trình `reasoning`:**
> - **❌ SAI (Bị từ chối)**: `"Phát hiện bất thường chi phí SageMaker do z-score vượt ngưỡng 3-sigma (3.42) trên phương sai ngày."`
> - **✅ ĐÚNG (Hợp lệ)**: `"Chi phí cụm SageMaker Notebook tăng đột biến 2.3 lần so với trung bình tuần trước, phát sinh lãng phí khoảng $400/ngày do máy chạy không tải (idle) liên tục trong 18 ngày."`

**Response example (Đang xử lý)**:

```json
{
  "status": "IN_PROGRESS",
  "audit_id": "audit-f92a10b4-93e1-4560-bf87-9d7a22ef3f22"
}
```

**Response example (Đã hoàn thành)**:

```json
{
  "status": "COMPLETED",
  "audit_id": "audit-f92a10b4-93e1-4560-bf87-9d7a22ef3f22",
  "anomaly": true,
  "severity": 0.85,
  "suggested_action": "SCHEDULE_SHUTDOWN",
  "reasoning": "Chi phí cụm SageMaker Notebook tăng đột biến 2.3 lần so với trung bình tuần trước, phát sinh lãng phí khoảng $400/ngày do máy chạy không tải (idle) liên tục trong 18 ngày.",
  "confidence": 0.92,
  "details": {
    "daily_waste_usd": 400.0,
    "runaway_days": 18,
    "affected_resource": "notebook-instance-training-v2",
    "ratio_increase": 2.3
  }
}
```

### SLA

| Metric | Target |
|---|---|
| **P99 latency** | < 10 ms (truy vấn DB trực tiếp bằng primary key `audit_id`) |
| **Throughput** | 300 requests / minute |

---

## Endpoint 3: `POST /v1/verify`

**Mục đích**: Xác minh tài nguyên bị bất thường đã được xử lý (containment) thành công và chi phí đã trở lại mức bình thường hay chưa.

### Request headers

| Header | Type | Required | Description |
|---|---|---|---|
| `X-Tenant-Id` | String | ✓ | Định danh tenant / squad chịu trách nhiệm chi phí |
| `X-Idempotency-Key` | String | ✓ | Khóa phân biệt giao dịch để chống double-run |
| `Authorization` | IAM SigV4 | ✓ | Xác thực liên dịch vụ |

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `action_taken.type` | enum | ✓ | Loại hành động ngăn chặn đã thực thi (`QUOTA_CAP`/`SCHEDULE_SHUTDOWN`...) |
| `action_taken.resource_id` | string | ✓ | ARN hoặc định danh tài nguyên đã bị xử lý |
| `action_taken.ts` | RFC3339 | ✓ | Thời điểm thực hiện hành động ngăn chặn |
| `post_state.signal_window` | array | ✓ | Chuỗi dữ liệu cập nhật sau khi xử lý để xác minh |

**Request example**:

```json
{
  "action_taken": {
    "type": "SCHEDULE_SHUTDOWN",
    "resource_id": "notebook-instance-training-v2",
    "ts": "2026-06-22T09:15:00Z"
  },
  "post_state": {
    "signal_window": [
      {
        "ts": "2026-06-22T10:00:00Z",
        "signal_name": "resource_utilization_metrics",
        "value": 0.0,
        "labels": {
          "resource_id": "notebook-instance-training-v2",
          "metric_name": "idle_hours_continuous"
        }
      }
    ]
  }
}
```

### Response body

| Field | Type | Description |
|---|---|---|
| `success` | bool | `true` nếu tài nguyên đã dừng tiêu tốn tiền lãng phí (hoặc đã tắt), ngược lại `false` |
| `regression_detected` | bool | `true` nếu hành động ngăn chặn vô tình gây ra lỗi hệ thống khác hoặc tăng vọt chi phí ở dịch vụ khác |
| `next_action` | enum | Đề xuất hành động tiếp theo: `DONE` (thành công), `RETRY` (thực hiện lại), `ESCALATE` (báo động đỏ khẩn cấp) |

**Response example**:

```json
{
  "success": true,
  "regression_detected": false,
  "next_action": "DONE"
}
```

---

## Endpoint 4: POST /v1/tenants/{tenant_id}/error-budget/reset

**Mục đích**: Reset thủ công ngân sách lỗi (Error Budget) cho một tenant cụ thể về trạng thái ban đầu và mở khóa chế độ Auto-containment (nếu trước đó bị khóa cứng do vượt hạn mức 1%).

### Path parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `tenant_id` | String | ✓ | Định danh tenant / squad cần reset ngân sách lỗi |

### Request headers

| Header | Type | Required | Description |
|---|---|---|---|
| `Authorization` | IAM SigV4 | ✓ | Xác thực quản trị viên (Admin) |

### Response body

Trả về mã trạng thái `200 OK`.

| Field | Type | Description |
|---|---|---|
| `tenant_id` | string | Định danh tenant đã reset |
| `status` | string | Trạng thái sau khi reset: `"UNLOCKED"` |
| `error_budget_burned` | float | Tỷ lệ ngân sách lỗi đã cháy sau khi reset: `0.0` |
| `message` | string | Giải trình hành động |

**Response example**:

```json
{
  "tenant_id": "tnt-squad12-finance",
  "status": "UNLOCKED",
  "error_budget_burned": 0.0,
  "message": "Error budget has been manually reset. Auto-containment is re-enabled."
}
```

---

## Endpoint 5: GET /v1/tenants/{tenant_id}/config và PUT /v1/tenants/{tenant_id}/config

**Mục đích**: Truy vấn hoặc cập nhật động cấu hình các ngưỡng và trọng số tính toán độ tự tin của một tenant.

### Path parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `tenant_id` | String | ✓ | Định danh tenant / squad cần cấu hình |

### Request headers

| Header | Type | Required | Description |
|---|---|---|---|
| `Authorization` | IAM SigV4 | ✓ | Xác thực quản trị viên (Admin) |

### Request body (Đối với PUT)

| Field | Type | Required | Description |
|---|---|---|---|
| `idle_threshold_normal` | integer | ✓ | Ngưỡng giờ không tải ở mức bình thường (giờ) |
| `idle_threshold_high` | integer | ✓ | Ngưỡng giờ không tải ở mức cao (giờ) |
| `confidence_weights` | object | ✓ | Trọng số dùng để tính điểm tin cậy toán học |
| `confidence_weights.missing_tags` | float | ✓ | Trọng số cho sự kiện thiếu thẻ tag |
| `confidence_weights.idle_hours` | float | ✓ | Trọng số cho thời gian không hoạt động |
| `confidence_weights.log_anomaly` | float | ✓ | Trọng số cho phát hiện log bất thường (Drain3) |

> [!IMPORTANT]
> **Quy định ràng buộc khi cập nhật cấu hình:**
> - Tổng giá trị của 3 trường trong `confidence_weights` (`missing_tags` + `idle_hours` + `log_anomaly`) **bắt buộc phải bằng đúng 1.0**. Nếu không, hệ thống sẽ trả về lỗi `400 Bad Request`.
> - Nếu `tenant_id` không tồn tại trong hệ thống quản trị, hệ thống sẽ trả về lỗi `404 Not Found`.

**Request example (PUT)**:

```json
{
  "idle_threshold_normal": 24,
  "idle_threshold_high": 72,
  "confidence_weights": {
    "missing_tags": 0.2,
    "idle_hours": 0.6,
    "log_anomaly": 0.2
  }
}
```

### Response body

Trả về mã trạng thái `200 OK`.

| Field | Type | Description |
|---|---|---|
| `idle_threshold_normal` | integer | Ngưỡng giờ không tải ở mức bình thường |
| `idle_threshold_high` | integer | Ngưỡng giờ không tải ở mức cao |
| `confidence_weights` | object | Trọng số tính điểm tin cậy đã lưu |

**Response example**:

```json
{
  "idle_threshold_normal": 24,
  "idle_threshold_high": 72,
  "confidence_weights": {
    "missing_tags": 0.2,
    "idle_hours": 0.6,
    "log_anomaly": 0.2
  }
}
```

---

## Endpoint 6: POST /v1/audit/{audit_id}/rollback

**Mục đích**: Ghi nhận một hành động hoàn tác can thiệp (rollback) được kích hoạt thủ công từ kỹ sư (hoặc từ CDO Platform), đồng thời tự động đánh dấu case phân tích tương ứng là False Positive và tính vào tỷ lệ cháy ngân sách lỗi SLO của Tenant.

### Path parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `audit_id` | String | ✓ | Mã định danh audit của case cần rollback |

### Request headers

| Header | Type | Required | Description |
|---|---|---|---|
| `X-Tenant-Id` | String | ✓ | Định danh tenant / squad chịu trách nhiệm |
| `Authorization` | IAM SigV4 | ✓ | Xác thực liên dịch vụ |

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `operator` | string | ✓ | Định danh kỹ sư thực hiện rollback |
| `rollback_ts` | RFC3339 | ✓ | Thời điểm thực hiện rollback |
| `reason_for_rollback` | string | optional | Lý do kỹ sư rollback |

**Request example**:

```json
{
  "operator": "user-dev-05",
  "rollback_ts": "2026-06-22T14:30:00Z",
  "reason_for_rollback": "Đây là cluster chạy thử nghiệm quan trọng, không phải runaway."
}
```

### Response body

Trả về mã trạng thái `200 OK`.

| Field | Type | Description |
|---|---|---|
| `audit_id` | string | Mã định danh audit |
| `status` | string | Trạng thái ghi nhận rollback: `"MARKED_AS_FALSE_POSITIVE"` |
| `tenant_id` | string | Tenant ID liên quan |
| `error_budget_burned_total` | string | Thông báo tỷ lệ cháy ngân sách lỗi hiện tại của Tenant |

**Response example**:

```json
{
  "audit_id": "audit-f92a10b4-93e1-4560-bf87-9d7a22ef3f22",
  "status": "MARKED_AS_FALSE_POSITIVE",
  "tenant_id": "tnt-squad12-finance",
  "error_budget_burned_total": "1.2% (Containment Lock Triggered)"
}
```

---

## Endpoint 7: GET /v1/tenants/{tenant_id}/anomalies

**Mục đích**: CDO Dashboard truy vấn danh sách lịch sử các vụ bất thường đã phát hiện trong quá khứ của một tenant để vẽ đồ thị overlay đè lên spend trend.

### Path parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `tenant_id` | String | ✓ | Định danh tenant / squad cần truy vấn lịch sử |

### Query parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `start_date` | Date (YYYY-MM-DD) | optional | Ngày bắt đầu truy vấn |
| `end_date` | Date (YYYY-MM-DD) | optional | Ngày kết thúc truy vấn |
| `min_severity` | float (0.0-1.0) | optional | Lọc theo độ nghiêm trọng tối thiểu |

### Request headers

| Header | Type | Required | Description |
|---|---|---|---|
| `Authorization` | IAM SigV4 | ✓ | Xác thực liên dịch vụ |

### Response body

Trả về mã trạng thái `200 OK`.

| Field | Type | Description |
|---|---|---|
| `tenant_id` | string | Định danh tenant |
| `total_count` | integer | Tổng số lượng kết quả khớp bộ lọc |
| `anomalies` | array | Danh sách các vụ bất thường |
| `anomalies[].audit_id` | string | Định danh phiên giao dịch |
| `anomalies[].ts` | RFC3339 | Thời gian ghi nhận bất thường |
| `anomalies[].anomaly` | boolean | Trạng thái bất thường |
| `anomalies[].severity` | float | Mức độ nghiêm trọng |
| `anomalies[].suggested_action` | string | Hành động ngăn chặn đã đề xuất |
| `anomalies[].reasoning` | string | Giải trình Finance-friendly |

**Response example**:

```json
{
  "tenant_id": "tnt-squad12-finance",
  "total_count": 1,
  "anomalies": [
    {
      "audit_id": "audit-f92a10b4-93e1-4560-bf87-9d7a22ef3f22",
      "ts": "2026-06-22T09:15:00Z",
      "anomaly": true,
      "severity": 0.85,
      "suggested_action": "SCHEDULE_SHUTDOWN",
      "reasoning": "Chi phí cụm SageMaker Notebook tăng đột biến 2.3 lần so với trung bình tuần trước, phát sinh lãng phí khoảng $400/ngày do máy chạy không tải (idle) liên tục trong 18 ngày."
    }
  ]
}
```

---

## Endpoint 8: POST /v1/tenants/{tenant_id}/history

**Mục đích**: CDO nạp hàng loạt (Bulk Ingestion) dữ liệu chi phí và hiệu năng quá khứ (ví dụ: 3 tháng) cho một tenant để thiết lập baseline ban đầu (Warm-up Window) hoặc chạy thử nghiệm backtest offline.

### Path parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `tenant_id` | String | ✓ | Định danh tenant / squad cần nạp lịch sử |

### Request headers

| Header | Type | Required | Description |
|---|---|---|---|
| `Authorization` | IAM SigV4 | ✓ | Xác thực liên dịch vụ |

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `signals` | array | ✓ | Danh sách các tín hiệu lịch sử cần import |
| `signals[].ts` | RFC3339 | ✓ | Thời điểm ghi nhận tín hiệu |
| `signals[].signal_name` | string | ✓ | Tên tín hiệu |
| `signals[].value` | float | ✓ | Giá trị đo lường |
| `signals[].labels` | object | optional | Metadata đi kèm |

**Request example**:

```json
{
  "signals": [
    {
      "ts": "2026-06-01T00:00:00Z",
      "signal_name": "daily_cur_spend_usd",
      "value": 50.0,
      "labels": {
        "resource_id": "notebook-instance-training-v2",
        "service": "SageMaker",
        "environment": "dev"
      }
    },
    {
      "ts": "2026-06-02T00:00:00Z",
      "signal_name": "daily_cur_spend_usd",
      "value": 52.0,
      "labels": {
        "resource_id": "notebook-instance-training-v2",
        "service": "SageMaker",
        "environment": "dev"
      }
    }
  ]
}
```

### Response body

Trả về mã trạng thái `200 OK`.

| Field | Type | Description |
|---|---|---|
| `tenant_id` | string | Định danh tenant |
| `imported_count` | integer | Số lượng bản ghi đã nạp thành công |

**Response example**:

```json
{
  "tenant_id": "tnt-squad12-finance",
  "imported_count": 2
}
```

---

## Endpoint 9: POST /v1/admin/backtest

**Mục đích**: Kích hoạt chạy đánh giá thuật toán phát hiện bất thường chi phí trên dữ liệu lịch sử đã nạp để xuất báo cáo nghiệm thu Backtest Report (Precision, Recall, F1, Confusion Matrix) theo yêu cầu của CFO.

### Request headers

| Header | Type | Required | Description |
|---|---|---|---|
| `Authorization` | IAM SigV4 | ✓ | Xác thực quản trị viên (Admin) |

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `tenant_id` | string | ✓ | Tenant cần chạy backtest |
| `start_date` | Date (YYYY-MM-DD) | ✓ | Ngày bắt đầu khoảng thời gian backtest |
| `end_date` | Date (YYYY-MM-DD) | ✓ | Ngày kết thúc khoảng thời gian backtest |
| `expected_anomalies` | array | ✓ | Danh sách các sự cố thực tế trong lịch sử để đối chiếu |
| `expected_anomalies[].ts` | Date (YYYY-MM-DD) | ✓ | Ngày xảy ra sự cố |
| `expected_anomalies[].resource_id` | string | ✓ | Tài nguyên bị sự cố |

**Request example**:

```json
{
  "tenant_id": "tnt-squad12-finance",
  "start_date": "2026-06-01",
  "end_date": "2026-06-22",
  "expected_anomalies": [
    {
      "ts": "2026-06-22",
      "resource_id": "notebook-instance-training-v2"
    }
  ]
}
```

### Response body

Trả về mã trạng thái `200 OK`.

| Field | Type | Description |
|---|---|---|
| `tenant_id` | string | Định danh tenant đã chạy backtest |
| `precision` | float | Chỉ số chính xác (Precision) |
| `recall` | float | Chỉ số phủ phủ (Recall) |
| `f1_score` | float | F1-Score |
| `confusion_matrix` | object | Ma trận nhầm lẫn |
| `confusion_matrix.true_positive` | integer | Số vụ bắt đúng |
| `confusion_matrix.false_positive` | integer | Số vụ báo động giả |
| `confusion_matrix.false_negative` | integer | Số vụ bỏ sót |
| `confusion_matrix.true_negative` | integer | Số ngày bình thường nhận diện đúng |

**Response example**:

```json
{
  "tenant_id": "tnt-squad12-finance",
  "precision": 1.0,
  "recall": 1.0,
  "f1_score": 1.0,
  "confusion_matrix": {
    "true_positive": 1,
    "false_positive": 0,
    "false_negative": 0,
    "true_negative": 21
  }
}
```

---

## Error codes

| Code | Meaning | CDO action |
|---|---|---|
| `400` | Invalid input schema, thiếu Header bắt buộc, hoặc tổng trọng số `confidence_weights` khác 1.0 | Không retry, kiểm tra dữ liệu đầu vào |
| `401` | Auth failed (AWS Signature) | Kiểm tra cấu hình IAM Role, Refresh credentials và thử lại |
| `404` | Không tìm thấy `tenant_id` hoặc `audit_id` trong hệ thống quản trị | Kiểm tra ID đã truyền xem có hợp lệ không |
| `429` | Rate-limited | Chờ đợi theo thông tin `Retry-After` và áp dụng exponential backoff |
| `503` | AI engine/Bedrock unavailable | CDO chuyển sang cơ chế fallback chạy quy tắc rule-based tĩnh |
