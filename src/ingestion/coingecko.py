"""
CoinGecko OHLCV ingest module.

Fetches BTC 1-min OHLCV candles from CoinGecko public API (no API key required).
Rate limit: 30 req/min on the free tier — one call per DAG run is safe.

Null guard: any null field in a candle row raises ValueError immediately.
This prevents NaN from propagating into features silently.
"""
import requests
import boto3
import io
import pandas as pd

COINGECKO_OHLCV_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlcv"
HEADERS = {"User-Agent": "crypto-volatility-mlops/1.0"}


def fetch_ohlcv(days: float = 0.1) -> list:
    """Fetch BTC 1-min OHLCV candles from CoinGecko (no API key required).

    days=0.1 is approximately 144 minutes of 1-min candles on the free tier.

    Raises ValueError on any null field — do not propagate NaN into features.
    Rate limit: 30 req/min. One call per DAG run is safe.

    Returns:
        list of lists: [[ts_ms, open, high, low, close, volume], ...]
    """
    resp = requests.get(
        COINGECKO_OHLCV_URL,
        params={"vs_currency": "usd", "days": days},
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    candles = resp.json()  # [[ts_ms, open, high, low, close, volume], ...]

    # Guard against null fields — raise rather than propagate NaN downstream
    for i, row in enumerate(candles):
        if any(v is None for v in row):
            raise ValueError(f"Null value in CoinGecko candle row {i}: {row}")

    return candles


def candles_to_dataframe(candles: list) -> pd.DataFrame:
    """Convert raw CoinGecko candle list to a sorted DataFrame.

    Args:
        candles: list of [ts_ms, open, high, low, close, volume]

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
        sorted by timestamp ascending.
    """
    df = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def write_raw_to_s3(df: pd.DataFrame, bucket: str, key: str) -> None:
    """Write raw OHLCV DataFrame to S3 as Parquet.

    Uses upload_fileobj for streaming upload without temp file.

    Args:
        df: OHLCV DataFrame
        bucket: S3 bucket name
        key: S3 object key (e.g. "raw/btc_ohlcv/20240101T000000Z.parquet")
    """
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    s3 = boto3.client("s3")
    s3.upload_fileobj(buf, bucket, key)
