"""Backfill Lambda — EventBridge-triggered every 30 minutes.

Scans DynamoDB for predictions written 25-40 minutes ago that have no
actual_label, fetches BTC price from CoinGecko to determine the actual
VOLATILE/CALM label, and writes it back via update_item.

Note: CoinGecko /coins/bitcoin/history is day-granular on the free tier.
      Phase 5 Airflow DAG can refine this using stored raw OHLCV data.
"""

import boto3
from boto3.dynamodb.conditions import Attr
import os
import requests
from datetime import datetime, timedelta, timezone
from decimal import Decimal

PREDICTIONS_TABLE = os.environ["PREDICTIONS_TABLE"]
ddb = boto3.resource("dynamodb")
table = ddb.Table(PREDICTIONS_TABLE)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
VOLATILITY_THRESHOLD = 0.02  # 2% swing = VOLATILE


def fetch_btc_price_at(dt: datetime) -> float:
    """Fetch BTC price closest to dt using CoinGecko /coins/bitcoin/history.

    Note: Free tier API returns daily price, not minute-granular.
    """
    date_str = dt.strftime("%d-%m-%Y")
    resp = requests.get(
        f"{COINGECKO_BASE}/coins/bitcoin/history",
        params={"date": date_str, "localization": "false"},
        timeout=10,
    )
    resp.raise_for_status()
    return float(resp.json()["market_data"]["current_price"]["usd"])


def compute_actual_label(prediction_timestamp: str) -> str:
    """Fetch BTC price at prediction time and 30 min later, compute label.

    Uses day-granular CoinGecko data. For more accuracy Phase 5 Airflow
    DAG can use stored OHLCV data for minute-level price comparison.
    """
    pred_dt = datetime.fromisoformat(prediction_timestamp.rstrip("Z")).replace(
        tzinfo=timezone.utc
    )
    try:
        later_dt = pred_dt + timedelta(minutes=30)
        price_at_pred = fetch_btc_price_at(pred_dt)
        price_at_later = fetch_btc_price_at(later_dt)
        swing = abs(price_at_later - price_at_pred) / price_at_pred
        return "VOLATILE" if swing > VOLATILITY_THRESHOLD else "CALM"
    except Exception:
        # Failed to fetch price — log but don't crash the Lambda
        return "UNKNOWN"


def handler(event, context):
    """Scan DynamoDB for predictions ~30 min old without actual_label and backfill."""
    now = datetime.now(timezone.utc)
    # Target predictions written between 25 and 40 minutes ago
    cutoff_start = (now - timedelta(minutes=40)).isoformat()
    cutoff_end = (now - timedelta(minutes=25)).isoformat()

    # Scan for records in the backfill window without actual_label
    result = table.scan(
        FilterExpression=(
            Attr("actual_label").not_exists()
            & Attr("timestamp").between(cutoff_start, cutoff_end)
        ),
        ProjectionExpression="prediction_id, #ts",
        ExpressionAttributeNames={"#ts": "timestamp"},
    )

    backfilled = 0
    for item in result.get("Items", []):
        actual_label = compute_actual_label(item["timestamp"])
        table.update_item(
            Key={"prediction_id": item["prediction_id"]},
            UpdateExpression="SET actual_label = :label, backfilled_at = :ts",
            ExpressionAttributeValues={
                ":label": actual_label,
                ":ts": datetime.now(timezone.utc).isoformat(),
            },
        )
        backfilled += 1

    return {"backfilled": backfilled, "scanned": len(result.get("Items", []))}
