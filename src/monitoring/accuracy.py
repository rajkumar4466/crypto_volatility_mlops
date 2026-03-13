"""
accuracy.py — Rolling prediction accuracy from DynamoDB backfilled actuals.

Reads the DynamoDB predictions table (written by Phase 4 Lambda serving) and computes
rolling accuracy over a configurable time window. The actual_label field is backfilled
approximately 30 minutes after prediction time; items without actual_label are excluded.

DynamoDB schema (from Phase 4 SERV-04, SERV-05):
    partition key: prediction_id (string)
    attributes:
        timestamp     (ISO string)     — prediction time
        features      (map)            — 12-feature dict at prediction time
        prediction    (string)         — "VOLATILE" | "CALM"
        probability   (number)         — model confidence
        model_version (string: "vN")  — e.g., "v3"
        actual_label  (string)         — "VOLATILE" | "CALM", backfilled ~30 min later
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

_MIN_ITEMS = 10  # Minimum number of labeled items required for a reliable accuracy estimate


def compute_rolling_accuracy(
    table_name: str,
    window_minutes: int = 120,
) -> Optional[float]:
    """Compute rolling prediction accuracy over a time window from DynamoDB.

    Scans the DynamoDB predictions table for items within the last `window_minutes`
    that have an actual_label field (backfilled by the backfill Lambda). Compares
    each item's prediction against its actual_label to compute accuracy.

    Args:
        table_name: DynamoDB table name (from env var PREDICTIONS_TABLE_NAME).
        window_minutes: Rolling window in minutes. Default 120 minutes (2 hours).
            Items older than this are excluded from accuracy computation.

    Returns:
        float in [0.0, 1.0] if >= 10 labeled items found in the window.
        None if fewer than 10 items found (insufficient data — e.g., first DAG cycles
        before backfill has populated actuals, or table is empty).

    Notes:
        - Uses paginated DynamoDB scan to handle tables with > 1MB of data.
        - Reserved word 'timestamp' is aliased via ExpressionAttributeNames.
        - Does not raise exceptions on empty tables — returns None cleanly.
    """
    cutoff = (datetime.utcnow() - timedelta(minutes=window_minutes)).isoformat()

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    items = []
    try:
        # Initial scan with FilterExpression for timestamp cutoff and actual_label presence
        # Note: 'timestamp' is a reserved word in DynamoDB expressions; we use the
        # Attr() helper here which boto3 handles transparently (no ExpressionAttributeNames
        # needed when using the condition expression builder).
        response = table.scan(
            FilterExpression=(
                boto3.dynamodb.conditions.Attr("timestamp").gte(cutoff)
                & boto3.dynamodb.conditions.Attr("actual_label").exists()
            ),
        )
        items.extend(response.get("Items", []))

        # Paginate through all results if table exceeds 1MB scan limit
        while "LastEvaluatedKey" in response:
            response = table.scan(
                FilterExpression=(
                    boto3.dynamodb.conditions.Attr("timestamp").gte(cutoff)
                    & boto3.dynamodb.conditions.Attr("actual_label").exists()
                ),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

    except Exception as exc:  # noqa: BLE001
        logger.warning("DynamoDB scan failed for table '%s': %s", table_name, exc)
        return None

    if len(items) < _MIN_ITEMS:
        logger.info(
            "Insufficient labeled items for accuracy: found=%d, min_required=%d "
            "(table=%s, window=%d min)",
            len(items),
            _MIN_ITEMS,
            table_name,
            window_minutes,
        )
        return None

    correct = sum(
        1
        for item in items
        if item.get("prediction") == item.get("actual_label")
    )
    accuracy = correct / len(items)

    logger.info(
        "Rolling accuracy: %.3f (%d/%d correct, window=%d min, table=%s)",
        accuracy,
        correct,
        len(items),
        window_minutes,
        table_name,
    )
    return accuracy
