"""Drift-triggered retraining, approval, promotion, and rollback."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import mlflow
import mlflow.sklearn
import pandas as pd
import requests
from mlflow import MlflowClient

from drift_detector import detect_drift
from pipeline import (
    EXPERIMENT_NAME,
    FEATURES,
    MODEL_NAME,
    build_model,
    latest_version,
    tracking_uri,
)

AUDIT_LOG_PATH = Path(__file__).resolve().parent / "outputs" / "audit_log.jsonl"
POST_DEPLOY_CYCLES = 24
POST_DEPLOY_PRECISION_THRESHOLD = 0.65


def append_audit(event: str, **detail) -> None:
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **detail,
    }
    with AUDIT_LOG_PATH.open("a") as handle:
        handle.write(json.dumps(entry) + "\n")


def classification_metrics(model, frame: pd.DataFrame) -> tuple[float, float, float]:
    X = frame[FEATURES].dropna()
    y_true = frame.loc[X.index, "anomaly_label"].to_numpy()
    raw = model.predict(X)
    y_pred = (raw == -1).astype(int)
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def register_staging(model, training_frame: pd.DataFrame, drift_score: float) -> tuple[str, str]:
    uri = tracking_uri()
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(EXPERIMENT_NAME)
    X = training_frame[FEATURES]
    anomaly_rate = float((model.predict(X) == -1).mean())

    with mlflow.start_run(run_name="drift-retrain") as run:
        mlflow.log_params(
            {
                "trigger": "combined_drift_gate",
                "training_strategy": "baseline_plus_recent_7d",
                "training_rows": len(X),
                "n_estimators": 150,
                "contamination": 0.03,
            }
        )
        mlflow.log_metrics(
            {
                "drift_score": drift_score,
                "train_anomaly_rate": anomaly_rate,
            }
        )
        mlflow.set_tags(
            {
                "approval_required": "true",
                "decision_state": "registered_staging",
            }
        )
        mlflow.sklearn.log_model(
            model,
            artifact_path="model",
            registered_model_name=MODEL_NAME,
            input_example=X.head(3),
        )

    client = MlflowClient(tracking_uri=uri)
    version = latest_version(client)
    client.set_registered_model_alias(MODEL_NAME, "staging", version)
    client.set_model_version_tag(MODEL_NAME, version, "approval_state", "staging")
    append_audit(
        "retrain_registered_staging",
        version=version,
        drift_score=drift_score,
        training_rows=len(X),
        run_id=run.info.run_id,
    )
    print(f"[retrain] Model v{version} registered as @staging")
    return version, run.info.run_id


def reload_server(url: str) -> None:
    try:
        response = requests.post(f"{url}/reload", timeout=10)
        response.raise_for_status()
        print(f"[retrain] serve.py reload: {response.json()}")
    except requests.RequestException as exc:
        print(f"[retrain] WARNING: serve reload skipped: {exc}")


def post_deploy_monitor(
    v2_version: str,
    v1_version: str,
    eval_path: str,
    serve_url: str,
    cycles: int = POST_DEPLOY_CYCLES,
    precision_threshold: float = POST_DEPLOY_PRECISION_THRESHOLD,
) -> None:
    uri = tracking_uri()
    client = MlflowClient(tracking_uri=uri)
    eval_frame = pd.read_csv(eval_path)

    for cycle in range(1, cycles + 1):
        model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@production")
        precision, recall, f1 = classification_metrics(model, eval_frame)
        print(
            f"post_deploy_monitor Cycle {cycle:02d}/{cycles} — "
            f"precision: {precision:.4f}  recall: {recall:.4f}  f1: {f1:.4f}"
        )
        append_audit(
            "post_deploy_cycle",
            cycle=cycle,
            version=v2_version,
            precision=precision,
            recall=recall,
            f1=f1,
        )
        if precision < precision_threshold:
            client.set_registered_model_alias(MODEL_NAME, "archived", v2_version)
            client.set_registered_model_alias(MODEL_NAME, "production", v1_version)
            append_audit(
                "auto_rollback_v2_to_v1",
                demoted_version=v2_version,
                restored_version=v1_version,
                trigger_precision=precision,
                cycle=cycle,
            )
            reload_server(serve_url)
            print(
                f"Rollback complete. v{v1_version} restored to @production. "
                f"v{v2_version} → @archived"
            )
            return
    append_audit("post_deploy_stable", version=v2_version, cycles=cycles)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--holdout")
    parser.add_argument("--post-deploy-eval")
    parser.add_argument("--threshold", type=float, default=0.15)
    parser.add_argument("--serve-url", default="http://localhost:8000")
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument(
        "--post-deploy-precision-threshold",
        type=float,
        default=POST_DEPLOY_PRECISION_THRESHOLD,
        help="Default 0.65; higher values are useful only for rollback-path testing.",
    )
    args = parser.parse_args()

    uri = tracking_uri()
    mlflow.set_tracking_uri(uri)
    reference = pd.read_csv(args.reference)
    current = pd.read_csv(args.current)
    drift = detect_drift(reference, current, args.threshold, report_label="retrain")
    print(f"[retrain] Drift score: {drift.score:.4f}")
    print(f"[retrain] Drift detected: {drift.is_drift}")
    if not drift.is_drift:
        append_audit("retrain_skipped_no_drift", score=drift.score)
        return

    client = MlflowClient(tracking_uri=uri)
    try:
        v1_version = client.get_model_version_by_alias(MODEL_NAME, "production").version
    except Exception as exc:
        raise RuntimeError("Train and register v1 before running retrain.py") from exc

    # Preserve both traffic regimes. Training only on seven drifted days made
    # the detector forget the historical distribution during local trials.
    training_frame = pd.concat([reference, current], ignore_index=True)
    model = build_model(contamination=0.03, n_estimators=150, random_state=42)
    model.fit(training_frame[FEATURES])
    print(
        f"[retrain] Sliding window rows: {len(training_frame)} "
        f"(baseline {len(reference)} + current {len(current)})"
    )

    if args.holdout:
        holdout = pd.read_csv(args.holdout)
        precision, recall, f1 = classification_metrics(model, holdout)
        v1_model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/{v1_version}")
        v1_precision, v1_recall, v1_f1 = classification_metrics(v1_model, holdout)
        print(
            f"Holdout baseline - v1 precision: {v1_precision:.4f}  "
            f"recall: {v1_recall:.4f}  f1: {v1_f1:.4f}"
        )
        print(
            f"Holdout validation — v2 precision: {precision:.4f}  "
            f"recall: {recall:.4f}  f1: {f1:.4f}"
        )
        append_audit(
            "holdout_validation",
            v2_precision=precision,
            v2_recall=recall,
            v2_f1=f1,
            v1_precision=v1_precision,
            v1_recall=v1_recall,
        )
        if precision < v1_precision:
            append_audit(
                "retrain_rejected_holdout_regression",
                v1_precision=v1_precision,
                v2_precision=precision,
            )
            raise RuntimeError(
                f"v2 holdout precision {precision:.4f} is below v1 {v1_precision:.4f}"
            )

    v2_version, retrain_run_id = register_staging(model, training_frame, drift.score)
    print(
        f"Drift detected. Model v{v2_version} registered as staging. "
        "Promote to production? [y/N]"
    )
    approved = args.auto_approve
    if not args.auto_approve:
        approved = input().strip().lower() == "y"
    if not approved:
        client.set_tag(retrain_run_id, "approval_decision", "declined")
        client.set_tag(retrain_run_id, "final_alias", "staging")
        append_audit("promotion_declined", version=v2_version)
        print(f"[retrain] v{v2_version} remains @staging")
        return

    client.set_registered_model_alias(MODEL_NAME, "production", v2_version)
    client.set_model_version_tag(MODEL_NAME, v2_version, "approval_state", "production")
    client.set_tag(retrain_run_id, "approval_decision", "approved")
    client.set_tag(retrain_run_id, "previous_production_version", str(v1_version))
    client.set_tag(retrain_run_id, "promoted_version", str(v2_version))
    client.set_tag(retrain_run_id, "final_alias", "production")
    append_audit(
        "promotion_approved",
        promoted_version=v2_version,
        previous_version=v1_version,
    )
    reload_server(args.serve_url)
    print(f"[retrain] v{v2_version} promoted to @production")

    if args.post_deploy_eval:
        post_deploy_monitor(
            v2_version=v2_version,
            v1_version=str(v1_version),
            eval_path=args.post_deploy_eval,
            serve_url=args.serve_url,
            precision_threshold=args.post_deploy_precision_threshold,
        )


if __name__ == "__main__":
    main()
