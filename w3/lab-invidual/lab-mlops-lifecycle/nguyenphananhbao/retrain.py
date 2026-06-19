"""
retrain.py — Orchestrator: detect drift → retrain v2 → register staging → approve → promote.
"""

import argparse
import os
import sys

# Ensure UTF-8 console output on Windows to avoid UnicodeEncodeError on unicode characters
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests
import pandas as pd
import mlflow
import mlflow.sklearn
from mlflow import MlflowClient
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

# Thêm thư mục hiện tại vào sys.path để import local
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drift_detector import detect_drift, log_to_mlflow  # noqa: E402

MODEL_NAME = "anomaly-detector"
EXPERIMENT_NAME = "anomaly-detection"
FEATURES = ["latency_p99", "error_rate", "rps"]
AUDIT_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs", "audit_log.jsonl")
POST_DEPLOY_CYCLES = 24          # Mô phỏng 24 chu kỳ giám sát post-deploy
POST_DEPLOY_PREC_THRESHOLD = 0.65  # Tự động rollback nếu precision của v2 giảm dưới ngưỡng này


def append_audit(event: str, detail: dict) -> None:
    """Ghi nhận sự kiện vào file log audit.jsonl."""
    import json
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
    entry = {"timestamp": __import__("datetime").datetime.utcnow().isoformat(), "event": event, **detail}
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def train_model_on_df(df: pd.DataFrame, contamination: float = 0.03, n_estimators: int = 100):
    """Huấn luyện IsolationForest trên DataFrame, trả về (model, scaler, anomaly_rate, n_rows)."""
    X = df[FEATURES].dropna()

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        contamination=contamination,
        n_estimators=n_estimators,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    labels = model.predict(X_scaled)
    anomaly_rate = float((labels == -1).mean())
    return model, scaler, anomaly_rate, len(X)


def register_new_version(
    model,
    scaler,
    anomaly_rate: float,
    training_rows: int,
    drift_score: float,
    current_data_path: str,
    tracking_uri: str,
) -> str:
    """Đăng ký model mới lên MLflow Registry và gán tag alias 'staging'."""
    import pickle
    import tempfile

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    X_sample = pd.read_csv(current_data_path)[FEATURES].head(3)

    with mlflow.start_run(run_name="retrain-triggered") as run:
        mlflow.log_param("trigger", "drift_detected")
        mlflow.log_param("drift_score", drift_score)
        mlflow.log_param("training_rows", training_rows)
        mlflow.log_param("features", ",".join(FEATURES))
        mlflow.log_metric("train_anomaly_rate", anomaly_rate)

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            pickle.dump(scaler, f)
            scaler_path = f.name
        mlflow.log_artifact(scaler_path, artifact_path="scaler")
        os.unlink(scaler_path)

        mlflow.sklearn.log_model(
            sk_model=model,
            artifact_path="model",
            registered_model_name=MODEL_NAME,
            input_example=X_sample,
        )

    client = MlflowClient(tracking_uri=tracking_uri)
    versions = client.search_model_versions(f"name='{MODEL_NAME}'")
    latest = max(versions, key=lambda v: int(v.version))

    client.set_registered_model_alias(MODEL_NAME, "staging", latest.version)
    print(f"[retrain] Registered {MODEL_NAME} v{latest.version} -> alias 'staging'")
    return latest.version


def promote_to_production(version: str, tracking_uri: str) -> None:
    client = MlflowClient(tracking_uri=tracking_uri)
    client.set_registered_model_alias(MODEL_NAME, "production", version)
    print(f"[retrain] Promoted v{version} -> alias 'production'")


def reload_serve(serve_url: str) -> None:
    try:
        resp = requests.post(f"{serve_url}/reload", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(f"[retrain] serve.py reloaded -> now serving v{data.get('version', '?')}")
    except requests.exceptions.ConnectionError:
        print(f"[retrain] WARNING: Could not reach serve.py at {serve_url}. Reload skipped.")
    except Exception as exc:
        print(f"[retrain] WARNING: Reload call failed: {exc}")


def post_deploy_monitor(
    v2_version: str,
    v1_version: str,
    post_deploy_eval_path: str,
    tracking_uri: str,
    serve_url: str,
    cycles: int = POST_DEPLOY_CYCLES,
    prec_threshold: float = POST_DEPLOY_PREC_THRESHOLD,
) -> None:
    """Giám sát hiệu năng của model v2 trên dữ liệu post-deploy trong N chu kỳ.
    Nếu precision giảm dưới ngưỡng, tự động rollback (trả lại v1 làm production).
    """
    eval_df = pd.read_csv(post_deploy_eval_path)
    if "anomaly_label" not in eval_df.columns:
        print("[post_deploy_monitor] WARNING: post_deploy_eval.csv has no anomaly_label — skipping.")
        return

    client = MlflowClient(tracking_uri=tracking_uri)
    model_uri = f"models:/{MODEL_NAME}@production"

    print(f"[post_deploy_monitor] Starting {cycles}-cycle post-deploy evaluation of v{v2_version}...")
    for cycle in range(1, cycles + 1):
        import mlflow.pyfunc
        model = mlflow.pyfunc.load_model(model_uri)
        X = eval_df[FEATURES].dropna()
        y_true = eval_df.loc[X.index, "anomaly_label"].values
        raw = model.predict(pd.DataFrame(X, columns=FEATURES))
        if hasattr(raw, "values"):
            raw = raw.values
        if set(raw).issubset({-1, 1}):
            y_pred = (raw == -1).astype(int)
        else:
            y_pred = raw.astype(int)
        tp = int(((y_pred == 1) & (y_true == 1)).sum())
        fp = int(((y_pred == 1) & (y_true == 0)).sum())
        fn = int(((y_pred == 0) & (y_true == 1)).sum())
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        print(f"[post_deploy_monitor] Cycle {cycle:02d}/{cycles} — precision: {precision:.4f}  recall: {recall:.4f}")
        append_audit("post_deploy_cycle", {"cycle": cycle, "precision": precision, "recall": recall, "v2": v2_version})

        if precision < prec_threshold:
            print(f"[post_deploy_monitor] Precision {precision:.4f} < threshold {prec_threshold} — triggering AUTO-ROLLBACK.")
            client.set_registered_model_alias(MODEL_NAME, "archived", v2_version)
            client.set_registered_model_alias(MODEL_NAME, "production", v1_version)
            append_audit("auto_rollback_v2_to_v1", {
                "demoted_version": v2_version,
                "restored_version": v1_version,
                "trigger_precision": precision,
                "threshold": prec_threshold,
                "cycle": cycle,
            })
            reload_serve(serve_url)
            print(f"[post_deploy_monitor] Rollback complete. v{v1_version} restored to @production. v{v2_version} -> @archived.")
            try:
                from metrics_util import push_event, push_active_version
                push_event("auto_rollback_v2_to_v1", v2_version)
                push_active_version(v1_version, "production")
                push_active_version(v2_version, "archived")
            except ImportError:
                pass
            return

    print(f"[post_deploy_monitor] v{v2_version} passed all {cycles} cycles. Stable in production.")
    append_audit("post_deploy_stable", {"version": v2_version, "cycles": cycles})


def main():
    parser = argparse.ArgumentParser(description="Drift-triggered retrain orchestrator")
    parser.add_argument("--reference", required=True, help="Baseline CSV")
    parser.add_argument("--current", required=True, help="Current production window CSV")
    parser.add_argument("--threshold", type=float, default=0.15)
    parser.add_argument("--serve-url", default="http://localhost:8000")
    parser.add_argument("--auto-approve", action="store_true", default=False)
    parser.add_argument("--contamination", type=float, default=0.03)
    parser.add_argument("--n-estimators", type=int, default=100)
    parser.add_argument("--holdout", default=None)
    parser.add_argument("--post-deploy-eval", default=None)
    args = parser.parse_args()

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")

    ref_df = pd.read_csv(args.reference)
    cur_df = pd.read_csv(args.current)
    print(f"[retrain] Reference rows : {len(ref_df)}")
    print(f"[retrain] Current rows   : {len(cur_df)}")

    print(f"[retrain] Running drift detection (threshold={args.threshold})...")
    drift_result = detect_drift(ref_df, cur_df, threshold=args.threshold, report_label="retrain")
    log_to_mlflow(drift_result)

    print(f"[retrain] Drift score    : {drift_result.score:.4f}")
    print(f"[retrain] Drift detected : {drift_result.is_drift}")

    if not drift_result.is_drift:
        print("[retrain] No drift detected — retrain not triggered. Exiting.")
        return

    print("[retrain] Drift confirmed. Building sliding-window training set (baseline + drift)...")
    baseline_df_train = ref_df.copy()
    drift_df_train = cur_df.copy()
    combined_df = pd.concat([baseline_df_train, drift_df_train], ignore_index=True)
    print(f"[retrain] Sliding window rows : {len(combined_df)}")

    model, scaler, anomaly_rate, n_rows = train_model_on_df(
        combined_df,
        contamination=args.contamination,
        n_estimators=args.n_estimators,
    )
    print(f"[retrain] New model anomaly rate: {anomaly_rate:.4f} on {n_rows} rows")

    if args.holdout:
        holdout_df = pd.read_csv(args.holdout)
        if "anomaly_label" in holdout_df.columns:
            # Đánh giá v2 ngay tại bộ nhớ trước khi đăng ký
            X_hold = holdout_df[FEATURES].dropna()
            y_true = holdout_df.loc[X_hold.index, "anomaly_label"].values
            X_scaled_hold = scaler.transform(X_hold)
            raw = model.predict(X_scaled_hold)
            y_pred = (raw == -1).astype(int)
            tp = int(((y_pred == 1) & (y_true == 1)).sum())
            fp = int(((y_pred == 1) & (y_true == 0)).sum())
            fn = int(((y_pred == 0) & (y_true == 1)).sum())
            prec_v2 = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec_v2 = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            print(f"Holdout validation — v2 precision: {prec_v2:.4f}  recall: {rec_v2:.4f}")
            append_audit("holdout_validation", {"v2_precision": prec_v2, "v2_recall": rec_v2})

    new_version = register_new_version(
        model, scaler, anomaly_rate, n_rows,
        drift_result.score, args.current, tracking_uri,
    )

    if args.auto_approve:
        approved = True
        print("[retrain] Auto-approve mode — skipping human gate.")
    else:
        print()
        print("=" * 60)
        print(f"  Drift score   : {drift_result.score:.4f}  (threshold {args.threshold})")
        print(f"  Drifted cols  : {drift_result.drifted_features}")
        print(f"  New version   : {MODEL_NAME} v{new_version} (alias: staging)")
        print(f"  Anomaly rate  : {anomaly_rate:.4f}")
        print("=" * 60)
        answer = input("  Promote staging -> production? [y/N] ").strip().lower()
        approved = answer == "y"

    if not approved:
        print(f"[retrain] Promotion declined. Model v{new_version} remains in staging.")
        return

    client = MlflowClient(tracking_uri=tracking_uri)
    try:
        v1_model = client.get_model_version_by_alias(MODEL_NAME, "production")
        v1_version = v1_model.version
    except Exception:
        v1_version = "1"
    append_audit("promote_v2", {"v2_version": new_version, "v1_version": v1_version})

    promote_to_production(new_version, tracking_uri)
    reload_serve(args.serve_url)
    print(f"[retrain] Pipeline complete. {MODEL_NAME} v{new_version} is now in production.")

    try:
        from metrics_util import push_event, push_active_version
        push_event("retrain_triggered", new_version)
        push_active_version(new_version, "production")
        push_active_version(v1_version, "archived")
    except ImportError:
        pass

    if args.post_deploy_eval:
        post_deploy_monitor(
            v2_version=new_version,
            v1_version=v1_version,
            post_deploy_eval_path=args.post_deploy_eval,
            tracking_uri=tracking_uri,
            serve_url=args.serve_url,
        )


if __name__ == "__main__":
    main()
