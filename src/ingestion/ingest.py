"""
Standalone ingest script. Run directly or call from Airflow PythonOperator.
Usage: python -m src.ingestion.ingest --bucket my-bucket --prefix raw/btc_ohlcv/

Fetches BTC OHLCV candles from Binance and writes to S3 as Parquet.
Binance public API: no key required, 1000 candles per request.
"""
import argparse
from datetime import datetime, timezone

from src.ingestion.binance import fetch_ohlcv, candles_to_dataframe, write_raw_to_s3


def main(bucket: str, prefix: str, interval: str = "1h", limit: int = 1000):
    """Fetch Binance OHLCV data and write to S3.

    Args:
        bucket: S3 bucket name
        prefix: S3 key prefix (e.g. "raw/btc_ohlcv/")
        interval: Candle interval (1h, 4h, etc.)
        limit: Number of candles to fetch (max 1000)

    Returns:
        DataFrame of fetched candles
    """
    print(f"Fetching BTC/USDT from Binance (interval={interval}, limit={limit})...")
    candles = fetch_ohlcv(symbol="BTCUSD", interval=interval, limit=limit)
    df = candles_to_dataframe(candles)
    print(
        f"Fetched {len(df)} candles. "
        f"Range: {df['timestamp'].min()} to {df['timestamp'].max()}"
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"{prefix}{ts}.parquet"
    write_raw_to_s3(df, bucket, key)
    print(f"Written to s3://{bucket}/{key}")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch BTC OHLCV from Binance and write to S3"
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--prefix", default="raw/btc_ohlcv/", help="S3 key prefix")
    parser.add_argument("--interval", default="1h", help="Candle interval (1h, 4h, etc.)")
    parser.add_argument("--limit", type=int, default=1000, help="Number of candles")
    args = parser.parse_args()
    main(args.bucket, args.prefix, args.interval, args.limit)
