"""
crypto_volatility_dag.py — Airflow DAG for the crypto volatility MLOps pipeline.

This DAG orchestrates the 7-phase pipeline that runs every 30 minutes:

    ingest -> compute_features -> predict -> retrain -> evaluate -> promote -> monitor

Trigger Rule Design
-------------------
Most tasks use the default ALL_SUCCESS trigger rule, meaning they are skipped if any
upstream task fails. Two tasks override this for resilience:

- retrain (TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS):
    Runs even if predict is skipped (e.g., no new predictions needed), but is still
    skipped if ingest or compute_features hard-failed. This prevents retraining on
    stale data while allowing flexible upstream conditions.

- promote (TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS):
    Runs even if evaluate is skipped (unlikely but safe), but is still skipped if
    retrain hard-failed. This prevents promoting a model that failed to train.

- monitor (TriggerRule.ALL_DONE):
    Always runs regardless of upstream outcome. The monitor task emits observability
    signals (metrics, alerts) for every run, including failed or partially-skipped
    runs. This is intentional — we need visibility into failures, not just successes.

Monitor Task Environment Variables
-----------------------------------
Required:
    S3_BUCKET               — S3 bucket name (contains reference features and model artifacts)
    PREDICTIONS_TABLE_NAME  — DynamoDB table name for prediction log (with backfilled actuals)

Optional (retrain trigger disabled if absent):
    AIRFLOW_HOST            — Airflow webserver base URL (e.g., http://localhost:8080)
    AIRFLOW_API_TOKEN       — Airflow JWT Bearer token for REST API auth
    RETRAIN_DAG_ID          — DAG ID to trigger on drift (default: crypto_volatility_pipeline)

Used by Terraform CloudWatch alarms (not by Python code directly):
    SNS_TOPIC_ARN           — SNS topic ARN for email alerts
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from functools import partial

import boto3
import pandas as pd

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

from src.monitoring.accuracy import compute_rolling_accuracy
from src.monitoring.alerts import publish_metrics
from src.monitoring.drift import FEATURE_NAMES, compute_drift
from src.monitoring.retrain_trigger import trigger_retrain_dag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Script runner (used by tasks 1-6)
# ---------------------------------------------------------------------------

def run_script(script_name: str, **kwargs) -> None:
    """Generic callable for running a Phase 1-4 script as an Airflow task.

    Each script handles its own business logic. The DAG is a thin orchestration
    layer that invokes scripts via subprocess and propagates failures via exit codes.

    Args:
        script_name: Filename under the scripts/ directory (e.g., 'ingest.py').
        **kwargs: Airflow context (injected by PythonOperator, unused here).

    Raises:
        Exception: If the script exits with a non-zero return code.
    """
    project_root = os.environ.get("PROJECT_ROOT", "/opt/airflow")
    script_path = os.path.join(project_root, "scripts", script_name)

    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=True,
        text=True,
    )

    # Always print stdout/stderr so logs appear in Airflow task logs
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        raise Exception(
            f"{script_name} failed with exit code {result.returncode}"
        )


# ---------------------------------------------------------------------------
# Monitor task callable (Task 7)
# ---------------------------------------------------------------------------

def _load_reference_features(s3_bucket: str) -> pd.DataFrame | None:
    """Load the reference feature distribution from S3.

    Returns None if the reference file does not exist (e.g., first run before
    model promotion has written the reference snapshot).
    """
    s3_key = "features/reference/reference_features.parquet"
    s3_path = f"s3://{s3_bucket}/{s3_key}"
    try:
        # pandas.read_parquet supports s3:// paths when s3fs is installed
        df = pd.read_parquet(s3_path)
        logger.info("Loaded reference features from %s: %d rows", s3_path, len(df))
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Reference features not found at %s — skipping drift detection: %s",
            s3_path,
            exc,
        )
        return None


def _load_recent_features(s3_bucket: str, n_rows: int = 60) -> pd.DataFrame | None:
    """Load recent feature rows from the Feast offline store in S3.

    The Feast offline store writes Parquet files partitioned by date under
    s3://{bucket}/feast/feature_store/. We load all available files, sort by
    event_timestamp descending, and return the last n_rows.

    Returns None if no feature files are found (pipeline not yet run).
    """
    import io

    s3_client = boto3.client("s3")
    prefix = "feast/feature_store/"

    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=s3_bucket, Prefix=prefix)
        keys = [
            obj["Key"]
            for page in pages
            for obj in page.get("Contents", [])
            if obj["Key"].endswith(".parquet")
        ]

        if not keys:
            logger.warning(
                "No Feast offline store Parquet files found at s3://%s/%s",
                s3_bucket,
                prefix,
            )
            return None

        frames = []
        for key in keys:
            obj = s3_client.get_object(Bucket=s3_bucket, Key=key)
            frames.append(pd.read_parquet(io.BytesIO(obj["Body"].read())))

        df = pd.concat(frames, ignore_index=True)
        if "event_timestamp" in df.columns:
            df = df.sort_values("event_timestamp", ascending=False)

        recent = df.head(n_rows)
        logger.info("Loaded %d recent feature rows from Feast offline store", len(recent))
        return recent

    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load recent features from S3: %s", exc)
        return None


def _get_model_version(s3_bucket: str) -> str | None:
    """Read the current champion model version from S3 current_metrics.json."""
    s3_client = boto3.client("s3")
    key = "models/current_metrics.json"
    try:
        obj = s3_client.get_object(Bucket=s3_bucket, Key=key)
        metrics = json.loads(obj["Body"].read().decode("utf-8"))
        version = metrics.get("version")
        logger.info("Current model version from S3: %s", version)
        return version
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read model version from s3://%s/%s: %s", s3_bucket, key, exc)
        return None


def _get_prediction_latency_ms() -> float | None:
    """Read recent Lambda invocation Duration from CloudWatch (last 5 minutes).

    Returns the average Duration in milliseconds, or None if CloudWatch data
    is unavailable (e.g., no invocations in the window, cold-start gap).
    """
    cw = boto3.client("cloudwatch")
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(minutes=5)
    try:
        response = cw.get_metric_statistics(
            Namespace="AWS/Lambda",
            MetricName="Duration",
            Dimensions=[{"Name": "FunctionName", "Value": os.environ.get("LAMBDA_FUNCTION_NAME", "crypto-volatility-predict")}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=["Average"],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            logger.debug("No Lambda Duration datapoints in last 5 minutes")
            return None
        avg_ms = datapoints[0]["Average"]
        logger.info("Lambda prediction latency: %.1f ms", avg_ms)
        return avg_ms
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not retrieve prediction latency from CloudWatch: %s", exc)
        return None


def run_monitor(**kwargs) -> None:
    """Task 7: Monitor pipeline — drift detection, accuracy tracking, metric publishing.

    This is the real monitor callable that replaces the placeholder run_script("monitor.py").
    It calls all four monitoring modules and wires them together as the observability
    backbone of the pipeline.

    Execution flow:
        1. Load reference features from S3 (skip drift if absent — first run)
        2. Load recent features from Feast offline store in S3
        3. Run KS-test drift detection across all 12 features
        4. Compute rolling accuracy from DynamoDB backfilled actuals
        5. Read current model version from S3 current_metrics.json
        6. Read prediction latency from CloudWatch Lambda metrics
        7. Publish all 5 CloudWatch metrics in a single put_metric_data call
        8. Trigger retraining DAG via Airflow REST API if drift detected
        9. Log a summary line

    Raises:
        Exception: Re-raises any exception after logging, so Airflow marks task as failed
            for visibility. A failed monitor task does NOT block the DAG from completing
            (this task runs with TriggerRule.ALL_DONE and has no downstream dependencies).
    """
    try:
        s3_bucket = os.environ["S3_BUCKET"]
        predictions_table = os.environ["PREDICTIONS_TABLE_NAME"]

        # Step 1 & 2: Load feature distributions
        reference_df = _load_reference_features(s3_bucket)
        recent_df = _load_recent_features(s3_bucket)

        # Step 3: Drift detection
        drift_detected = False
        drift_score = 0.0
        drifted_features = []

        if reference_df is not None and recent_df is not None:
            drift_detected, drift_score, drifted_features = compute_drift(
                reference_df, recent_df, FEATURE_NAMES
            )
        else:
            logger.warning(
                "Skipping drift detection: reference_df=%s, recent_df=%s",
                "present" if reference_df is not None else "missing",
                "present" if recent_df is not None else "missing",
            )

        # Step 4: Rolling accuracy
        rolling_accuracy = compute_rolling_accuracy(predictions_table)

        # Step 5: Model version
        model_version = _get_model_version(s3_bucket)

        # Step 6: Prediction latency
        prediction_latency_ms = _get_prediction_latency_ms()

        # Step 7: Retrain count (static 0 for now; enhanced post-Phase 6)
        retrain_count = 0

        # Step 8: Publish CloudWatch metrics
        publish_metrics(
            rolling_accuracy=rolling_accuracy,
            drift_score=drift_score if reference_df is not None else None,
            model_version_str=model_version,
            prediction_latency_ms=prediction_latency_ms,
            retrain_count=retrain_count,
        )

        # Step 9: Trigger retraining if drift detected and API token available
        retrain_triggered = False
        airflow_api_token = os.environ.get("AIRFLOW_API_TOKEN")
        if drift_detected and airflow_api_token:
            airflow_host = os.environ.get("AIRFLOW_HOST", "http://localhost:8080")
            retrain_dag_id = os.environ.get("RETRAIN_DAG_ID", "crypto_volatility_pipeline")
            trigger_retrain_dag(airflow_host, retrain_dag_id, airflow_api_token)
            retrain_triggered = True
        elif drift_detected and not airflow_api_token:
            logger.warning(
                "Drift detected but AIRFLOW_API_TOKEN not set — skipping retrain trigger"
            )

        # Step 10: Summary log
        logger.info(
            "Monitor: accuracy=%s, drift_score=%.2f, drifted_features=%s, retrain_triggered=%s",
            f"{rolling_accuracy:.3f}" if rolling_accuracy is not None else "None",
            drift_score,
            drifted_features,
            retrain_triggered,
        )
        print(
            f"Monitor: accuracy={rolling_accuracy}, drift_score={drift_score:.2f}, "
            f"drifted_features={drifted_features}, retrain_triggered={retrain_triggered}"
        )

    except Exception:
        logger.exception("Monitor task failed — re-raising for Airflow visibility")
        raise


# ---------------------------------------------------------------------------
# DAG default args
# ---------------------------------------------------------------------------

default_args = {
    "owner": "mlops",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "start_date": datetime(2026, 1, 1),
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
}

# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

with DAG(
    dag_id="crypto_volatility_pipeline",
    description="End-to-end crypto volatility MLOps pipeline: ingest → features → predict → retrain → evaluate → promote → monitor",
    schedule_interval="*/30 * * * *",
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["crypto", "mlops", "volatility"],
) as dag:

    # Task 1: Ingest raw OHLCV data from CoinGecko / Binance
    ingest = PythonOperator(
        task_id="ingest",
        python_callable=partial(run_script, "ingest.py"),
    )

    # Task 2: Compute technical features (RSI, MACD, Bollinger Bands, etc.)
    compute_features = PythonOperator(
        task_id="compute_features",
        python_callable=partial(run_script, "compute_features.py"),
    )

    # Task 3: Generate predictions using the current champion model
    predict = PythonOperator(
        task_id="predict",
        python_callable=partial(run_script, "predict.py"),
    )

    # Task 4: Retrain the model on recent data
    # trigger_rule=NONE_FAILED_MIN_ONE_SUCCESS: run even if predict was skipped,
    # but skip if ingest/compute_features hard-failed (would train on stale data)
    retrain = PythonOperator(
        task_id="retrain",
        python_callable=partial(run_script, "retrain.py"),
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    )

    # Task 5: Evaluate the newly trained model against the current champion
    evaluate = PythonOperator(
        task_id="evaluate",
        python_callable=partial(run_script, "evaluate.py"),
    )

    # Task 6: Promote the challenger model if it outperforms the champion
    # trigger_rule=NONE_FAILED_MIN_ONE_SUCCESS: run even if evaluate was skipped
    # (safe), but skip if retrain hard-failed (nothing to promote)
    promote = PythonOperator(
        task_id="promote",
        python_callable=partial(run_script, "promote.py"),
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    )

    # Task 7: Monitor — drift detection, accuracy tracking, CloudWatch metrics, retrain trigger
    # trigger_rule=ALL_DONE: always runs — we need visibility into failures too.
    # run_monitor() calls all four monitoring modules (drift, accuracy, alerts, retrain_trigger).
    # A failed monitor task is re-raised for Airflow visibility but has no downstream dependents.
    monitor = PythonOperator(
        task_id="monitor",
        python_callable=run_monitor,
        trigger_rule=TriggerRule.ALL_DONE,
    )

    # ---------------------------------------------------------------------------
    # Dependency chain
    # ---------------------------------------------------------------------------
    ingest >> compute_features >> predict >> retrain >> evaluate >> promote >> monitor
