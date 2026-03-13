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
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta
from functools import partial

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

# ---------------------------------------------------------------------------
# Script runner
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

    # Task 7: Emit metrics, alerts, and observability signals
    # trigger_rule=ALL_DONE: always runs — we need visibility into failures too
    monitor = PythonOperator(
        task_id="monitor",
        python_callable=partial(run_script, "monitor.py"),
        trigger_rule=TriggerRule.ALL_DONE,
    )

    # ---------------------------------------------------------------------------
    # Dependency chain
    # ---------------------------------------------------------------------------
    ingest >> compute_features >> predict >> retrain >> evaluate >> promote >> monitor
