"""Train, log, and register the payment anomaly detector."""

import argparse
import os
from pathlib import Path

import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow import MlflowClient
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

EXPERIMENT_NAME = "anomaly-detection"
MODEL_NAME = "anomaly-detector"
FEATURES = ["latency_p99", "error_rate", "rps"]


def tracking_uri() -> str:
    local_store = Path(__file__).resolve().parent / "mlruns"
    return os.environ.get("MLFLOW_TRACKING_URI", local_store.as_uri())


def load_frame(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path, parse_dates=["timestamp"])
    missing = [name for name in FEATURES if name not in frame.columns]
    if missing:
        raise ValueError(f"Missing columns in {csv_path}: {missing}")
    return frame.dropna(subset=FEATURES)


def build_model(
    contamination: float = 0.03,
    n_estimators: int = 150,
    random_state: int = 42,
) -> Pipeline:
    return Pipeline(
        steps=[
            ("scale", StandardScaler()),
            (
                "isolation_forest",
                IsolationForest(
                    contamination=contamination,
                    n_estimators=n_estimators,
                    random_state=random_state,
                    n_jobs=-1,
                ),
            ),
        ]
    )


def latest_version(client: MlflowClient) -> str:
    versions = client.search_model_versions(f"name='{MODEL_NAME}'")
    if not versions:
        raise RuntimeError(f"No registered versions found for {MODEL_NAME}")
    return str(max(versions, key=lambda item: int(item.version)).version)


def train_and_register(
    data_path: str,
    alias: str = "production",
    contamination: float = 0.03,
    n_estimators: int = 150,
    random_state: int = 42,
    run_name: str = "baseline-v1",
) -> dict:
    uri = tracking_uri()
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    frame = load_frame(data_path)
    X = frame[FEATURES]
    model = build_model(contamination, n_estimators, random_state)
    model.fit(X)
    predictions = model.predict(X)
    anomaly_rate = float((predictions == -1).mean())

    with mlflow.start_run(run_name=run_name) as run:
        mlflow.log_params(
            {
                "contamination": contamination,
                "n_estimators": n_estimators,
                "random_state": random_state,
                "training_rows": len(X),
                "features": ",".join(FEATURES),
                "serving_preprocessing": "StandardScaler bundled in sklearn Pipeline",
            }
        )
        mlflow.log_metrics(
            {
                "train_anomaly_rate": anomaly_rate,
                "feature_count": float(len(FEATURES)),
            }
        )
        model_info = mlflow.sklearn.log_model(
            sk_model=model,
            artifact_path="model",
            registered_model_name=MODEL_NAME,
            input_example=X.head(3),
        )

    client = MlflowClient(tracking_uri=uri)
    version = latest_version(client)
    client.set_registered_model_alias(MODEL_NAME, alias, version)
    client.set_model_version_tag(MODEL_NAME, version, "training_data", str(data_path))
    client.set_model_version_tag(MODEL_NAME, version, "approval_state", alias)

    result = {
        "run_id": run.info.run_id,
        "version": version,
        "alias": alias,
        "anomaly_rate": anomaly_rate,
        "training_rows": len(X),
        "model_uri": model_info.model_uri,
        "tracking_uri": uri,
    }
    print(f"[pipeline] Run ID       : {result['run_id']}")
    print(f"[pipeline] Training rows : {len(X)}")
    print(f"[pipeline] Anomaly rate  : {anomaly_rate:.4f}")
    print(f"[pipeline] Registered    : {MODEL_NAME} v{version} -> @{alias}")
    print(f"[pipeline] Tracking URI  : {uri}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--alias", default="production")
    parser.add_argument("--contamination", type=float, default=0.03)
    parser.add_argument("--n-estimators", type=int, default=150)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()
    train_and_register(
        data_path=args.data,
        alias=args.alias,
        contamination=args.contamination,
        n_estimators=args.n_estimators,
        random_state=args.random_state,
    )


if __name__ == "__main__":
    main()
