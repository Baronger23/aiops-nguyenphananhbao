# Telemetry Contract - Task Force 2 (FinOps Watch)

<!-- Owner: Nhóm AI
     Signed by: AI Lead + CDO Leads × 2-3 + Reviewer panel
     Date signed: 2026-06-25 (W11 T5)
     🔒 FREEZE - no change without formal change request -->

## Mục đích

Định nghĩa **các tín hiệu (signals) chi phí và tài nguyên** mà nhóm CDO cần thu thập và chuẩn hóa từ hạ tầng AWS để cung cấp cho AI engine phân tích bất thường.

## Versioning

- **Current version**: `v1.0`
- **Evolution**: Chỉ bổ sung các trường không phá vỡ tính tương thích ngược (backward-compatible additions). Mọi thay đổi lớn sẽ được thảo luận trong Task Force và bump version.

---

## Signals required

Nhóm CDO bắt buộc phải chuẩn bị và cung cấp các tín hiệu sau:

### Signal 1: `daily_cur_spend_usd`

| Attribute | Value |
|---|---|
| **Type** | gauge |
| **Labels** | `tenant_id` (bắt buộc), `resource_id` (bắt buộc), `service` (EC2/SageMaker/RDS...), `linked_account_id`, `squad_owner`, `environment` (dev/sandbox/prod), `billing_period` |
| **Unit** | USD |
| **Frequency** | Mỗi 24 giờ (cập nhật theo chu kỳ ghi nhận AWS CUR) |
| **Emit point** | AWS CUR S3 bucket + Athena query / Cost Explorer API -> CDO Data Pipeline -> AI API |
| **Retention** | 90 ngày hot để phục vụ backtest và cửa sổ khởi động (Warm-up Window) |
| **Used for** | Phát hiện chi phí tăng vọt đột biến (spike) tổng thể hoặc theo dịch vụ/squad. Khớp nối trực tiếp với tài nguyên cụ thể để thực hiện auto-containment. |
| **Emit SLA** | < 4 giờ từ khi AWS cập nhật CUR S3 hoặc Cost Explorer kết xuất dữ liệu. |

> [!IMPORTANT]
> **Quy định ranh giới cho nhãn `resource_id` trong daily_cur_spend_usd:**
> - Đối với các dòng chi phí có tài nguyên cụ thể, CDO bắt buộc phải trích xuất và điền ARN hoặc Resource ID đầy đủ.
> - **Quy tắc Fallback & Cụm thông tin định vị không gian (Spatial Metadata Matrix)**: Đối với các chi phí không thể ánh xạ cụ thể (Data Transfer, Taxes), CDO bắt buộc phải gán giá trị mặc định là `unallocated-unmapped` hoặc `service-level-aggregate`. 
> - Đồng thời, CDO bắt buộc phải cung cấp trường `fallback_context` bên trong `labels` chứa thông tin định vị địa lý/hạ tầng:
>   + `linked_account_id`: ID tài khoản AWS liên kết.
>   + `vpc_id`: ID của VPC phát sinh chi phí truyền dữ liệu.
>   + `cost_category`: Danh mục chi phí (ví dụ: `DataTransfer-Out-Bytes`).
>   + `usage_type`: Loại sử dụng cụ thể (ví dụ: `APN1-DataTransfer-Out-Bytes`).
> - Cụ thể:
>   + Sử dụng `"unallocated-unmapped"` cho chi phí không rõ nguồn gốc/không có tag.
>   + Sử dụng `"service-level-aggregate"` cho chi phí dùng chung của toàn dịch vụ (như phí truyền dữ liệu).

**Schema example (Tài nguyên xác định rõ ràng)**:

```json
{
  "ts": "2026-06-22T00:00:00Z",
  "tenant_id": "tnt-squad12-finance",
  "signal_name": "daily_cur_spend_usd",
  "value": 412.50,
  "labels": {
    "resource_id": "arn:aws:sagemaker:ap-southeast-1:123456789012:notebook-instance/notebook-instance-training-v2",
    "service": "SageMaker",
    "linked_account_id": "123456789012",
    "squad_owner": "squad-prediction",
    "environment": "dev"
  } 
}
```

**Schema example (Fallback - Chi phí dùng chung Data Transfer)**:

```json
{
  "ts": "2026-06-22T00:00:00Z",
  "tenant_id": "tnt-squad12-finance",
  "signal_name": "daily_cur_spend_usd",
  "value": 250.00,
  "labels": {
    "resource_id": "service-level-aggregate",
    "service": "EC2",
    "linked_account_id": "123456789012",
    "squad_owner": "squad-prediction",
    "environment": "dev",
    "fallback_context": {
      "linked_account_id": "123456789012",
      "vpc_id": "vpc-0abcdef123456",
      "cost_category": "DataTransfer-Out-Bytes",
      "usage_type": "APN1-DataTransfer-Out-Bytes"
    }
  }
}
```

---

### Signal 2: `resource_utilization_metrics`

| Attribute | Value |
|---|---|
| **Type** | gauge |
| **Labels** | `tenant_id` (bắt buộc), `resource_id`, `resource_type` (EC2/SageMaker notebook...), `squad_owner`, `environment` |
| **Unit** | Percent / Hours |
| **Frequency** | Mỗi 24 giờ |
| **Emit point** | CloudWatch Metrics -> CDO Data Pipeline -> AI API |
| **Retention** | 30 ngày |
| **Used for** | Nhận diện tài nguyên không hoạt động (idle resources) như máy ảo có CPU < 5% hoặc SageMaker notebook không có tương tác để đề xuất containment. |

**Schema example**:

```json
{
  "ts": "2026-06-22T00:00:00Z",
  "tenant_id": "tnt-squad12-finance",
  "signal_name": "resource_utilization_metrics",
  "value": 18.0,
  "labels": {
    "resource_id": "notebook-instance-training-v2",
    "resource_type": "SageMaker-Notebook",
    "squad_owner": "squad-prediction",
    "environment": "dev",
    "metric_name": "idle_hours_continuous"
  }
}
```

---

### Signal 3: `resource_tag_status`

| Attribute | Value |
|---|---|
| **Type** | event |
| **Labels** | `tenant_id` (bắt buộc), `resource_id`, `resource_type`, `squad_owner`, `missing_tags` |
| **Unit** | Count |
| **Frequency** | On-event / Mỗi 24 giờ quét một lần |
| **Emit point** | AWS Config / Tag Editor Scan -> CDO Data Pipeline -> AI API |
| **Retention** | 30 ngày |
| **Used for** | Phát hiện các tài nguyên bị gán tag sai (mis-tagged) hoặc thiếu các tag bắt buộc (`Owner`, `Environment`, `Project`). |

**Schema example**:

```json
{
  "ts": "2026-06-22T09:00:00Z",
  "tenant_id": "tnt-squad12-finance",
  "signal_name": "resource_tag_status",
  "value": 1.0,
  "labels": {
    "resource_id": "arn:aws:ec2:us-east-1:123456789012:instance/i-0abcdef123456789",
    "resource_type": "EC2-Instance",
    "squad_owner": "unknown",
    "missing_tags": "Owner,Project"
  }
}
```

---

## Cross-cutting requirements

*   **Bắt buộc có Tenant ID**: Mọi signal payload gửi lên AI engine bắt buộc phải có trường `tenant_id` đại diện cho tài khoản/squad tương ứng.
*   **Không chứa thông tin nhạy cảm (No PII)**: Tuyệt đối không gửi email cá nhân, số điện thoại hoặc dữ liệu nhạy cảm của khách hàng trong trường labels. Tên tài nguyên (resource_id) phải được ẩn danh hóa nếu chứa thông tin nhạy cảm.
*   **Định dạng thời gian**: Tất cả timestamp phải sử dụng định dạng RFC3339 UTC với độ chính xác đến hàng giây (second precision).
