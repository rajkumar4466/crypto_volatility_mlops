"""
S3 model registry with promotion gate for the crypto volatility MLOps pipeline.

This module implements the champion/challenger pattern:
  - First run (no current_metrics.json): challenger always promotes.
  - Subsequent runs: challenger promotes only if challenger_f1 > champion_f1.
  - Either way, an ONNX artifact lands in S3 under models/ and a
    promotion.json decision record lands under runs/{run_id}/.

Public interface:
    promote_or_archive(bucket, run_id, challenger_f1, onnx_path, challenger_metrics)
        -> (decision: "promoted" | "rejected", champion_f1: float)

    backup_run_artifacts(bucket, run_id, metrics, params)
        -> None  (writes runs/{run_id}/metrics.json and runs/{run_id}/params.json)

Environment variables consumed:
    AWS credentials are picked up by boto3 from the standard chain
    (env vars, ~/.aws/credentials, EC2 instance role, etc.).
    S3_BUCKET is read by the caller (training/train.py), not here.
"""

import json
import logging
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def promote_or_archive(
    bucket: str,
    run_id: str,
    challenger_f1: float,
    onnx_path: str,
    challenger_metrics: dict,
) -> tuple:
    """Compare challenger against the current champion; promote or archive.

    Promotion logic:
        - If models/current_metrics.json does not exist → first run → always promote.
        - If challenger_f1 > champion_f1 → promote (replaces current.onnx).
        - Otherwise → archive challenger as models/v{run_id}.onnx (current unchanged).

    S3 layout after this call:
        models/current.onnx          — best model seen so far (promoted only)
        models/current_metrics.json  — champion metadata
        models/v{run_id}.onnx        — archived copy of either old champion or rejected challenger
        runs/{run_id}/promotion.json — decision record for this run

    Args:
        bucket:             S3 bucket name.
        run_id:             Unique run identifier (typically wandb.run.id).
        challenger_f1:      F1 score of the challenger model.
        onnx_path:          Local filesystem path to the challenger ONNX file.
        challenger_metrics: Full metrics dict for this run (logged to S3 JSON).

    Returns:
        (decision, champion_f1) where decision is "promoted" or "rejected" and
        champion_f1 is the F1 of the champion *before* this run (0.0 on first run).
    """
    s3 = boto3.client("s3")

    # ------------------------------------------------------------------
    # 1. Load champion metrics — handle first-run case gracefully
    # ------------------------------------------------------------------
    try:
        obj = s3.get_object(Bucket=bucket, Key="models/current_metrics.json")
        champion = json.loads(obj["Body"].read())
        champion_f1 = float(champion["f1"])
        champion_run_id = champion.get("run_id", "unknown")
        logger.info(
            "Champion loaded: run_id=%s f1=%.4f", champion_run_id, champion_f1
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchKey":
            # First run — no champion yet; challenger always wins
            champion_f1 = 0.0
            champion_run_id = None
            logger.info("No current_metrics.json found — first run, will promote.")
        else:
            raise

    # ------------------------------------------------------------------
    # 2. Promotion vs. rejection decision
    # ------------------------------------------------------------------
    if challenger_f1 > champion_f1:
        decision = _promote(
            s3=s3,
            bucket=bucket,
            run_id=run_id,
            onnx_path=onnx_path,
            champion_run_id=champion_run_id,
            challenger_f1=challenger_f1,
            challenger_metrics=challenger_metrics,
        )
    else:
        decision = _archive(
            s3=s3,
            bucket=bucket,
            run_id=run_id,
            onnx_path=onnx_path,
        )

    # ------------------------------------------------------------------
    # 3. Write promotion decision record (both branches)
    # ------------------------------------------------------------------
    _write_promotion_record(
        s3=s3,
        bucket=bucket,
        run_id=run_id,
        decision=decision,
        challenger_f1=challenger_f1,
        champion_f1=champion_f1,
        challenger_metrics=challenger_metrics,
    )

    logger.info(
        "Promotion result: %s (challenger F1=%.4f, champion F1=%.4f)",
        decision,
        challenger_f1,
        champion_f1,
    )
    return decision, champion_f1


def backup_run_artifacts(
    bucket: str,
    run_id: str,
    metrics: dict,
    params: dict,
) -> None:
    """Write runs/{run_id}/metrics.json and runs/{run_id}/params.json to S3.

    Called unconditionally after training so every run is auditable regardless
    of the promotion decision.

    Args:
        bucket:  S3 bucket name.
        run_id:  Unique run identifier (typically wandb.run.id).
        metrics: Dict with at least {"accuracy", "f1", "roc_auc"} keys.
        params:  GridSearchCV best_params_ dict.
    """
    s3 = boto3.client("s3")

    _put_json(
        s3=s3,
        bucket=bucket,
        key=f"runs/{run_id}/metrics.json",
        payload={
            "run_id": run_id,
            "metrics": metrics,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    _put_json(
        s3=s3,
        bucket=bucket,
        key=f"runs/{run_id}/params.json",
        payload={
            "run_id": run_id,
            "params": params,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    logger.info("Backed up metrics + params for run_id=%s", run_id)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _promote(
    *,
    s3,
    bucket: str,
    run_id: str,
    onnx_path: str,
    champion_run_id,
    challenger_f1: float,
    challenger_metrics: dict,
) -> str:
    """Archive the current champion (if any), then promote challenger to current."""
    # Archive the old champion ONNX before overwriting current.onnx
    if champion_run_id:
        try:
            s3.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": "models/current.onnx"},
                Key=f"models/v{champion_run_id}.onnx",
            )
            logger.info(
                "Archived previous champion as models/v%s.onnx", champion_run_id
            )
        except Exception:
            # No current.onnx on very first run — not an error
            logger.debug(
                "Could not archive models/current.onnx (may not exist yet) — skipping."
            )

    # Write new current model
    s3.upload_file(onnx_path, bucket, "models/current.onnx")
    logger.info("Uploaded challenger as models/current.onnx")

    # Write new champion metrics
    _put_json(
        s3=s3,
        bucket=bucket,
        key="models/current_metrics.json",
        payload={
            "f1": challenger_f1,
            "run_id": run_id,
            "metrics": challenger_metrics,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    return "promoted"


def _archive(
    *,
    s3,
    bucket: str,
    run_id: str,
    onnx_path: str,
) -> str:
    """Archive challenger without touching current champion."""
    s3.upload_file(onnx_path, bucket, f"models/v{run_id}.onnx")
    logger.info("Archived challenger as models/v%s.onnx (champion unchanged)", run_id)
    return "rejected"


def _write_promotion_record(
    *,
    s3,
    bucket: str,
    run_id: str,
    decision: str,
    challenger_f1: float,
    champion_f1: float,
    challenger_metrics: dict,
) -> None:
    """Write runs/{run_id}/promotion.json to S3."""
    _put_json(
        s3=s3,
        bucket=bucket,
        key=f"runs/{run_id}/promotion.json",
        payload={
            "decision": decision,
            "run_id": run_id,
            "challenger_f1": challenger_f1,
            "champion_f1": champion_f1,
            "timestamp": datetime.utcnow().isoformat(),
            "challenger_metrics": challenger_metrics,
        },
    )


def _put_json(*, s3, bucket: str, key: str, payload: dict) -> None:
    """Helper: serialize payload to JSON and PUT to S3."""
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, default=str),
        ContentType="application/json",
    )
    logger.debug("Wrote s3://%s/%s", bucket, key)
