# SUBMIT.md — Kết quả chạy các chaos scenarios và stress tests

## Thông tin cá nhân

- **Họ tên:** Nguyễn Phan Anh Bảo
- **Decision engine:** Rule-based (`config.yaml`)
- **Môi trường chạy:** Windows 11, Docker Desktop (WSL2), Python 3.12

---

## 1. Scenario 1 — Action thành công (HighLatency trên payment-svc)

**Lệnh tiêm lỗi:**
```bash
bash data-pack/scripts/inject_fault.sh latency ronki-payment-svc 500ms
```

**Nhật ký logs của Orchestrator:**
```json
{"ts": "2026-06-18T03:58:54.753890+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighLatency", "service": "payment-svc", "severity": "warning"}
{"ts": "2026-06-18T03:58:54.753977+00:00", "level": "INFO", "event_type": "DECIDE_RUNBOOK", "alertname": "HighLatency", "service": "payment-svc", "runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-18T03:58:54.754005+00:00", "level": "INFO", "event_type": "BLAST_RADIUS_OK", "service": "payment-svc"}
{"ts": "2026-06-18T03:58:54.754055+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": true}
{"ts": "2026-06-18T03:58:54.863258+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "payment-svc", "returncode": 0, "stdout": "[DRY-RUN] would execute: docker restart ronki-payment-svc", "stderr": ""}
{"ts": "2026-06-18T03:58:54.863346+00:00", "level": "INFO", "event_type": "DRY_RUN_PASS", "runbook": "runbooks/restart_service.sh", "service": "payment-svc"}
{"ts": "2026-06-18T03:58:54.863430+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": false}
{"ts": "2026-06-18T03:59:01.313810+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "payment-svc", "returncode": 0, "stdout": "[restart_service] Restarting ronki-payment-svc...\nronki-payment-svc\n[restart_service] Waiting 5s for ronki-payment-svc to come up...\n[restart_service] ronki-payment-svc is running.", "stderr": ""}
{"ts": "2026-06-18T03:59:01.313917+00:00", "level": "INFO", "event_type": "ACTION_EXECUTED", "runbook": "runbooks/restart_service.sh", "service": "payment-svc"}
{"ts": "2026-06-18T03:59:01.314014+00:00", "level": "INFO", "event_type": "VERIFY_START", "service": "payment-svc", "normalized_service": "payment-svc", "timeout_s": 60}
{"ts": "2026-06-18T03:59:01.325250+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "normalized_service": "payment-svc", "sample": 1, "latency_p99_ms": 248.28048780487808, "up": 1.0, "latency_ok": true, "up_ok": true}
{"ts": "2026-06-18T03:59:11.355547+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "normalized_service": "payment-svc", "sample": 2, "latency_p99_ms": 248.25735294117646, "up": 1.0, "latency_ok": true, "up_ok": true}
{"ts": "2026-06-18T03:59:21.364640+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "normalized_service": "payment-svc", "sample": 3, "latency_p99_ms": 248.16071428571428, "up": 1.0, "latency_ok": true, "up_ok": true}
{"ts": "2026-06-18T03:59:21.364685+00:00", "level": "INFO", "event_type": "VERIFY_PASS", "service": "payment-svc", "samples": 3}
{"ts": "2026-06-18T03:59:21.364784+00:00", "level": "INFO", "event_type": "ACTION_SUCCESS", "alertname": "HighLatency", "service": "payment-svc", "runbook": "runbooks/restart_service.sh"}
```

**Đánh giá:** Thành công. p99 latency hồi phục về mức tốt (~248ms) nhỏ hơn ngưỡng 500ms sau khi container được khởi động lại thành công.

---

## 2. Scenario 2 — Action thất bại $\rightarrow$ Rollback (verify fail)

**Thiết lập:** Tạm đặt ngưỡng `latency_p99_max_ms: 1` trong `baseline.json` để kích hoạt verify fail.

**Nhật ký logs của Orchestrator:**
```json
{"ts": "2026-06-18T04:03:27.736187+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "InstanceDown", "service": "checkout-svc", "severity": "critical"}
{"ts": "2026-06-18T04:03:27.736272+00:00", "level": "INFO", "event_type": "DECIDE_RUNBOOK", "alertname": "InstanceDown", "service": "checkout-svc", "runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-18T04:03:27.736301+00:00", "level": "INFO", "event_type": "BLAST_RADIUS_OK", "service": "checkout-svc"}
{"ts": "2026-06-18T04:03:27.736348+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "checkout-svc", "dry_run": true}
{"ts": "2026-06-18T04:03:27.835353+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "checkout-svc", "returncode": 0, "stdout": "[DRY-RUN] would execute: docker restart ronki-checkout-svc", "stderr": ""}
{"ts": "2026-06-18T04:03:27.835446+00:00", "level": "INFO", "event_type": "DRY_RUN_PASS", "runbook": "runbooks/restart_service.sh", "service": "checkout-svc"}
{"ts": "2026-06-18T04:03:27.835553+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "checkout-svc", "dry_run": false}
{"ts": "2026-06-18T04:03:33.056546+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "checkout-svc", "returncode": 0, "stdout": "[restart_service] Restarting ronki-checkout-svc...\nronki-checkout-svc\n[restart_service] Waiting 5s for ronki-checkout-svc to come up...\n[restart_service] ronki-checkout-svc is running.", "stderr": ""}
{"ts": "2026-06-18T04:03:33.056608+00:00", "level": "INFO", "event_type": "ACTION_EXECUTED", "runbook": "runbooks/restart_service.sh", "service": "checkout-svc"}
{"ts": "2026-06-18T04:03:33.056671+00:00", "level": "INFO", "event_type": "VERIFY_START", "service": "checkout-svc", "normalized_service": "checkout-svc", "timeout_s": 60}
{"ts": "2026-06-18T04:03:33.079070+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "normalized_service": "checkout-svc", "sample": 1, "latency_p99_ms": null, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-18T04:03:43.087429+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "normalized_service": "checkout-svc", "sample": 2, "latency_p99_ms": 248.5, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-18T04:03:53.106787+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "normalized_service": "checkout-svc", "sample": 3, "latency_p99_ms": 248.47635243597733, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-18T04:04:03.134279+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "normalized_service": "checkout-svc", "sample": 4, "latency_p99_ms": 248.48520847959776, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-18T04:04:13.155815+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "normalized_service": "checkout-svc", "sample": 5, "latency_p99_ms": 248.489154364186, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-18T04:04:23.180704+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "checkout-svc", "normalized_service": "checkout-svc", "sample": 6, "latency_p99_ms": 248.49135585465902, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-18T04:04:33.181166+00:00", "level": "WARNING", "event_type": "VERIFY_FAIL", "service": "checkout-svc", "samples": 6}
{"ts": "2026-06-18T04:04:33.181281+00:00", "level": "WARNING", "event_type": "ROLLBACK_TRIGGERED", "service": "checkout-svc", "rollback_runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-18T04:04:33.181304+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "checkout-svc", "dry_run": false}
{"ts": "2026-06-18T04:04:39.413213+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "checkout-svc", "returncode": 0, "stdout": "[restart_service] Restarting ronki-checkout-svc...\nronki-checkout-svc\n[restart_service] Waiting 5s for ronki-checkout-svc to come up...\n[restart_service] ronki-checkout-svc is running.", "stderr": ""}
{"ts": "2026-06-18T04:04:39.413304+00:00", "level": "INFO", "event_type": "ROLLBACK_EXECUTED", "service": "checkout-svc", "rollback_runbook": "runbooks/restart_service.sh"}
```

**Đánh giá:** Thành công. Khi độ trễ p99 vượt quá ngưỡng giả lập cực thấp (1ms), hàm verify bị quá thời gian 60s và trả về thất bại. Hệ thống ngay lập tức kích hoạt runbook rollback cho `checkout-svc`.

---

## 3. Scenario 3 — Circuit Breaker (3 lần lỗi liên tiếp)

**Nhật ký logs của Orchestrator:**
```json
{"ts": "2026-06-18T04:03:28.173460+00:00", "level": "ERROR", "event_type": "ACTION_EXEC_FAIL", "runbook": "runbooks/restart_service.sh", "service": "payment-svc"}
...
{"ts": "2026-06-18T04:04:39.413304+00:00", "level": "INFO", "event_type": "ROLLBACK_EXECUTED", "service": "checkout-svc", "rollback_runbook": "runbooks/restart_service.sh"}
...
{"ts": "2026-06-18T04:04:40.679057+00:00", "level": "INFO", "event_type": "ROLLBACK_EXECUTED", "service": "payment-svc", "rollback_runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-18T04:04:40.679075+00:00", "level": "ERROR", "event_type": "CIRCUIT_BREAKER_HALT", "consecutive_failures": 3, "threshold": 3, "message": "Automation halted. Manual intervention required."}
{"ts": "2026-06-18T04:04:42.801634+00:00", "level": "ERROR", "event_type": "CIRCUIT_BREAKER_HALT", "message": "Circuit open — polling suspended."}
```

**Đánh giá:** Thành công. Khi phát sinh liên tiếp 3 lỗi (gồm 1 lỗi thực thi runbook và 2 lỗi xác minh verify trên checkout-svc / payment-svc), cầu dao điện bảo vệ hệ thống lập tức mở (`CIRCUIT_OPEN`), suspend toàn bộ các hoạt động polling tự động để kỹ sư can thiệp bằng tay.

---

## 4. Scenario 4 — Multi-step transactional rollback

**Nhật ký logs của Orchestrator:**
```json
{"ts": "2026-06-18T04:06:14.463630+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "MultiStepDeploy", "service": "api-gateway", "severity": "critical"}
{"ts": "2026-06-18T04:06:14.463695+00:00", "level": "INFO", "event_type": "DECIDE_RUNBOOK", "alertname": "MultiStepDeploy", "service": "api-gateway", "runbook": "runbooks/multi_step_deploy.sh"}
{"ts": "2026-06-18T04:06:14.463807+00:00", "level": "INFO", "event_type": "BLAST_RADIUS_OK", "service": "api-gateway"}
{"ts": "2026-06-18T04:06:14.463926+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh", "service": "api-gateway", "dry_run": true}
{"ts": "2026-06-18T04:06:14.561992+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh", "service": "api-gateway", "returncode": 0, "stdout": "[DRY-RUN] would execute: full 3-step deploy on ronki-api-gateway", "stderr": ""}
{"ts": "2026-06-18T04:06:14.562045+00:00", "level": "INFO", "event_type": "DRY_RUN_PASS", "runbook": "runbooks/multi_step_deploy.sh", "service": "api-gateway"}
{"ts": "2026-06-18T04:06:14.562113+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh --step-a", "service": "api-gateway", "dry_run": false}
{"ts": "2026-06-18T04:06:14.649335+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh --step-a", "service": "api-gateway", "returncode": 0, "stdout": "[multi_step_deploy] step-A: draining traffic from ronki-api-gateway...\nronki-api-gateway\n[multi_step_deploy] step-A complete.", "stderr": ""}
{"ts": "2026-06-18T04:06:14.649396+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh --step-b", "service": "api-gateway", "dry_run": false}
{"ts": "2026-06-18T04:06:17.852780+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh --step-b", "service": "api-gateway", "returncode": 0, "stdout": "[multi_step_deploy] step-B: applying new config to ronki-api-gateway...\nronki-api-gateway\n[multi_step_deploy] step-B complete.", "stderr": ""}
{"ts": "2026-06-18T04:06:17.852868+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh --step-c", "service": "api-gateway", "dry_run": false}
{"ts": "2026-06-18T04:06:17.936607+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh --step-c", "service": "api-gateway", "returncode": 1, "stdout": "[multi_step_deploy] step-C: re-enabling traffic for ronki-api-gateway...\n[multi_step_deploy] SIMULATED FAILURE FOR STEP C", "stderr": ""}
{"ts": "2026-06-18T04:06:17.936690+00:00", "level": "ERROR", "event_type": "TRANSACTIONAL_STEP_FAIL", "step": "runbooks/multi_step_deploy.sh --step-c", "service": "api-gateway", "completed_before_failure": ["runbooks/multi_step_deploy.sh --step-a", "runbooks/multi_step_deploy.sh --step-b"]}
{"ts": "2026-06-18T04:06:17.936730+00:00", "level": "WARNING", "event_type": "TRANSACTIONAL_ROLLBACK_STEP", "step": "runbooks/multi_step_deploy.sh --rollback-b", "service": "api-gateway"}
{"ts": "2026-06-18T04:06:17.936756+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh --rollback-b", "service": "api-gateway", "dry_run": false}
{"ts": "2026-06-18T04:06:22.202632+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh --rollback-b", "service": "api-gateway", "returncode": 0, "stdout": "[multi_step_deploy] rollback-B: reverting config on ronki-api-gateway...\nronki-api-gateway\n[multi_step_deploy] rollback-B complete.", "stderr": ""}
{"ts": "2026-06-18T04:06:22.202718+00:00", "level": "WARNING", "event_type": "TRANSACTIONAL_ROLLBACK_STEP", "step": "runbooks/multi_step_deploy.sh --rollback-a", "service": "api-gateway"}
{"ts": "2026-06-18T04:06:22.202750+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh --rollback-a", "service": "api-gateway", "dry_run": false}
{"ts": "2026-06-18T04:06:24.207182+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh --rollback-a", "service": "api-gateway", "returncode": 0, "stdout": "[multi_step_deploy] rollback-A: restoring traffic to ronki-api-gateway...\nronki-api-gateway\n[multi_step_deploy] rollback-A complete.", "stderr": ""}
{"ts": "2026-06-18T04:06:24.207257+00:00", "level": "INFO", "event_type": "TRANSACTIONAL_ROLLBACK_COMPLETE", "service": "api-gateway", "rolled_back": ["runbooks/multi_step_deploy.sh --rollback-b", "runbooks/multi_step_deploy.sh --rollback-a"]}
```

**Đánh giá:** Thành công mỹ mãn. Bước C gặp lỗi `exit 1`, hệ thống lập tức thực hiện hoàn tác các bước đã hoàn thành theo đúng thứ tự đảo ngược (LIFO): hoàn tác bước B (`--rollback-b`) trước, sau đó mới hoàn tác bước A (`--rollback-a`). Log hiển thị chính xác danh sách `rolled_back` trong sự kiện `TRANSACTIONAL_ROLLBACK_COMPLETE`.

---

## 5. Scenario 5 — Concurrent alert race (Tranh chấp tài nguyên)

**Nhật ký logs của Orchestrator:**
```json
{"ts": "2026-06-18T04:10:16.365787+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighLatency", "service": "payment-svc", "severity": "warning"}
...
{"ts": "2026-06-18T04:10:16.366216+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighLatency", "service": "inventory-svc", "severity": "warning"}
{"ts": "2026-06-18T04:10:16.366669+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighErrorRate", "service": "payment-svc", "severity": "critical"}
...
{"ts": "2026-06-18T04:10:16.367502+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "inventory-svc", "dry_run": true}
...
{"ts": "2026-06-18T04:10:16.367933+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh", "service": "api-gateway", "dry_run": true}
{"ts": "2026-06-18T04:10:16.368004+00:00", "level": "WARNING", "event_type": "SERVICE_LOCK_BUSY", "service": "payment-svc", "message": "Another runbook is executing for this service; skipping duplicate"}
```

**Đánh giá:** Thành công. Các dịch vụ khác nhau (`payment-svc`, `inventory-svc`, `api-gateway`) hoàn toàn chạy song song và thực thi runbook cùng một lúc không cản trở nhau. Ngược lại, khi có hai cảnh báo khác nhau đồng thời xảy ra trên cùng một dịch vụ `payment-svc`, cơ chế mutex per-service hoạt động chính xác và khóa loại trừ, chặn đứng cảnh báo thứ 2 và log `SERVICE_LOCK_BUSY`.

---

## 6. Scenario 6 — Quyết định Hallucination (Chống ảo tưởng LLM)

**Lệnh tiêm lỗi giả lập quyết định sai lệch:**
Cấu hình ánh xạ `TestHallucination → runbooks/nonexistent_runbook.sh` nằm ngoài registry hợp lệ.

**Nhật ký logs của Orchestrator:**
```json
{"ts": "2026-06-18T04:14:31.600262+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "TestHallucination", "service": "payment-svc", "severity": "critical"}
{"ts": "2026-06-18T04:14:31.600350+00:00", "level": "ERROR", "event_type": "DECISION_VALIDATION_FAILED", "bad_runbook": "runbooks/nonexistent_runbook.sh", "alertname": "TestHallucination", "raw_decision": "runbooks/nonexistent_runbook.sh", "action": "escalate_no_auto_action"}
```

**Đánh giá:** Thành công. Hệ thống nhận diện quyết định runbook không thuộc whitelist của `runbook_registry`, ngay lập tức chặn lại và log lỗi `DECISION_VALIDATION_FAILED`. Tuyệt đối không sinh tiến trình con hay chạy thử lệnh sai lệch.
