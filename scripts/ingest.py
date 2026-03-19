"""Airflow wrapper: Ingest BTC OHLCV data from Binance to S3.

Fetches 90 days of 15-min candles on first run (no existing data),
or latest 1000 candles on subsequent runs (incremental).
"""
import os
import sys

sys.path.insert(0, os.environ.get("PROJECT_ROOT", "/home/ec2-user/crypto_volatility_mlops"))

from datetime import datetime, timezone
from src.ingestion.binance import fetch_ohlcv, fetch_ohlcv_historical, candles_to_dataframe, write_raw_to_s3

bucket = os.environ["S3_BUCKET"]
prefix = "raw/btc_ohlcv/"
interval = "15m"
backfill_days = int(os.environ.get("BACKFILL_DAYS", "90"))

# Check if raw data already exists in S3
import boto3
s3 = boto3.client("s3")
paginator = s3.get_paginator("list_objects_v2")
pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
existing_keys = [
    obj["Key"] for page in pages for obj in page.get("Contents", [])
    if obj["Key"].endswith(".parquet")
]

if not existing_keys:
    # First run: backfill historical data
    print(f"No existing data — backfilling {backfill_days} days of {interval} candles from Binance...")
    candles = fetch_ohlcv_historical(symbol="BTCUSD", interval=interval, days=backfill_days)
else:
    # Incremental: fetch latest 1000 candles
    print(f"Found {len(existing_keys)} existing files — fetching latest 1000 candles...")
    candles = fetch_ohlcv(symbol="BTCUSD", interval=interval, limit=1000)

df = candles_to_dataframe(candles)
print(f"Fetched {len(df)} candles. Range: {df['timestamp'].min()} to {df['timestamp'].max()}")

ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
key = f"{prefix}{ts}.parquet"
write_raw_to_s3(df, bucket, key)
print(f"Written to s3://{bucket}/{key}")
