"""
Standalone ingest script. Run directly or call from Airflow PythonOperator.
Usage: python -m src.ingestion.ingest --bucket my-bucket --prefix raw/btc_ohlcv/

Fetches BTC OHLCV candles from CoinGecko and writes to S3 as Parquet.
One call per DAG run — stays within free-tier rate limit (30 req/min).
"""
import argparse
from datetime import datetime, timezone

from src.ingestion.coingecko import fetch_ohlcv, candles_to_dataframe, write_raw_to_s3


def main(bucket: str, prefix: str, days: float = 0.1):
    """Fetch CoinGecko OHLCV data and write to S3.

    Args:
        bucket: S3 bucket name
        prefix: S3 key prefix (e.g. "raw/btc_ohlcv/")
        days: Number of days of data to fetch (0.1 ≈ 144 candles)

    Returns:
        DataFrame of fetched candles
    """
    print(f"Fetching BTC OHLCV from CoinGecko (days={days})...")
    candles = fetch_ohlcv(days=days)
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
        description="Fetch BTC OHLCV from CoinGecko and write to S3"
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--prefix", default="raw/btc_ohlcv/", help="S3 key prefix")
    parser.add_argument(
        "--days", type=float, default=0.1,
        help="Days of data to fetch (0.1 ≈ 144 1-min candles)"
    )
    args = parser.parse_args()
    main(args.bucket, args.prefix, args.days)
