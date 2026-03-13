"""
alerts.py — CloudWatch metric publisher for the crypto volatility MLOps pipeline.

Publishes exactly 5 custom metrics to the CryptoVolatility/Monitoring CloudWatch namespace
in a single put_metric_data API call. Keeping to 5 metrics respects the CloudWatch free
tier (10 always-free custom metrics — this plan uses half the budget).

CloudWatch alarms (SNS email triggers) are Terraform resources defined in Plan 06-02.
This module only publishes data; alarm thresholds are infrastructure concerns.

Free-tier constraint: Do NOT add more metrics here — the project budget is 10 total custom
metrics and other namespaces may contribute the remaining 5.
"""

import logging
from datetime import datetime
from typing import Optional, Union

import boto3

logger = logging.getLogger(__name__)

_NAMESPACE = "CryptoVolatility/Monitoring"


def publish_metrics(
    rolling_accuracy: Optional[float],
    drift_score: Optional[float],
    model_version_str: Optional[Union[str, int]],
    prediction_latency_ms: Optional[float],
    retrain_count: Optional[int],
) -> None:
    """Publish up to 5 monitoring metrics to CloudWatch in a single API call.

    All parameters are optional (can be None). Metrics with None values are skipped
    to avoid CloudWatch InvalidParameterValueException. At least one non-None value
    is required for the call to proceed; if all are None, the function returns early
    without making an API call.

    Args:
        rolling_accuracy: Prediction accuracy over the rolling window, [0.0, 1.0].
            None if insufficient labeled data (fewer than 10 items in DynamoDB).
        drift_score: Fraction of features that drifted, [0.0, 1.0].
            None if drift detection was skipped (e.g., reference file not found).
        model_version_str: Current champion model version string (e.g., "v12") or
            integer. Converted to int by stripping the "v" prefix. None if unavailable.
        prediction_latency_ms: Lambda Duration in milliseconds from CloudWatch Logs.
            None if CloudWatch data is unavailable (first run or cold-start gap).
        retrain_count: Number of drift-triggered DAG runs today. 0 on first run.
            None to skip publishing.

    Notes:
        - model_version_str is encoded as an integer for CloudWatch (strips "v" prefix).
        - All 5 metrics are published under namespace 'CryptoVolatility/Monitoring'.
        - Timestamp is set to UTC now (within CloudWatch's ±2-week acceptance window).
        - Skipped metrics (None) are logged at DEBUG level.
    """
    now = datetime.utcnow()

    # Convert model_version_str to int, handling both "v12" strings and bare ints
    model_version_int: Optional[int] = None
    if model_version_str is not None:
        try:
            if isinstance(model_version_str, int):
                model_version_int = model_version_str
            else:
                model_version_int = int(str(model_version_str).lstrip("v"))
        except (ValueError, AttributeError) as exc:
            logger.warning("Could not convert model_version_str '%s' to int: %s", model_version_str, exc)

    # Build MetricData list — only include metrics with non-None values
    metric_candidates = [
        {
            "MetricName": "rolling_accuracy",
            "Value": rolling_accuracy,
            "Unit": "None",
            "Timestamp": now,
        },
        {
            "MetricName": "drift_score",
            "Value": drift_score,
            "Unit": "None",
            "Timestamp": now,
        },
        {
            "MetricName": "model_version",
            "Value": model_version_int,
            "Unit": "Count",
            "Timestamp": now,
        },
        {
            "MetricName": "prediction_latency",
            "Value": prediction_latency_ms,
            "Unit": "Milliseconds",
            "Timestamp": now,
        },
        {
            "MetricName": "retrain_count",
            "Value": retrain_count,
            "Unit": "Count",
            "Timestamp": now,
        },
    ]

    metric_data = []
    for candidate in metric_candidates:
        if candidate["Value"] is None:
            logger.debug("Skipping metric '%s': value is None", candidate["MetricName"])
        else:
            metric_data.append(candidate)

    if not metric_data:
        logger.warning("All monitoring metrics are None — skipping CloudWatch put_metric_data call")
        return

    client = boto3.client("cloudwatch")
    client.put_metric_data(
        Namespace=_NAMESPACE,
        MetricData=metric_data,
    )

    published_names = [m["MetricName"] for m in metric_data]
    logger.info(
        "Published %d metrics to CloudWatch namespace '%s': %s",
        len(metric_data),
        _NAMESPACE,
        published_names,
    )
