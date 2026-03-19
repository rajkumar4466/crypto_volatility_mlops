"""
Binance OHLCV ingest module.

Fetches BTC/USDT klines from Binance public API (no API key required).
No rate limit concerns — public endpoints allow 1200 req/min.

Returns the same DataFrame format as the CoinGecko module:
  columns: timestamp, open, high, low, close, volume
  timestamp: milliseconds since epoch

Null guard: any null field raises ValueError immediately.
"""
import time
import requests
import boto3
import io
import pandas as pd

BINANCE_KLINES_URL = "https://api.binance.us/api/v3/klines"


def fetch_ohlcv(symbol: str = "BTCUSD", interval: str = "1h", limit: int = 1000) -> list:
    """Fetch OHLCV klines from Binance public API.

    Args:
        symbol: Trading pair (default BTCUSDT)
        interval: Candle interval (1m, 5m, 15m, 1h, 4h, 1d, etc.)
        limit: Number of candles (max 1000)

    Returns:
        list of lists: [[ts_ms, open, high, low, close, volume], ...]
    """
    resp = requests.get(
        BINANCE_KLINES_URL,
        params={"symbol": symbol, "interval": interval, "limit": min(limit, 1000)},
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()

    return _parse_klines(raw)


def fetch_ohlcv_historical(
    symbol: str = "BTCUSD",
    interval: str = "15m",
    days: int = 90,
) -> list:
    """Fetch historical klines by paginating backwards from now.

    Binance returns max 1000 candles per request. This function pages
    backwards using endTime to collect the requested number of days.

    Args:
        symbol: Trading pair
        interval: Candle interval
        days: Number of days of history to fetch

    Returns:
        list of lists: [[ts_ms, open, high, low, close, volume], ...]
    """
    # Interval to milliseconds mapping for pagination
    interval_ms = {
        "1m": 60_000, "5m": 300_000, "15m": 900_000,
        "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
    }
    candle_ms = interval_ms.get(interval, 900_000)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 86_400_000)

    all_candles = []
    cursor = start_ms

    while cursor < now_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "limit": 1000,
        }
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=30)
        resp.raise_for_status()
        raw = resp.json()

        if not raw:
            break

        batch = _parse_klines(raw)
        all_candles.extend(batch)

        # Move cursor past the last candle we received
        cursor = int(raw[-1][0]) + candle_ms
        print(f"  Fetched {len(batch)} candles (total: {len(all_candles)})")

    # Deduplicate by timestamp
    seen = set()
    unique = []
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique.append(c)

    print(f"Fetched {len(unique)} unique candles over {days} days")
    return unique


def _parse_klines(raw: list) -> list:
    """Parse raw Binance kline response into [ts, o, h, l, c, v] rows."""
    candles = []
    for i, row in enumerate(raw):
        ts = int(row[0])
        o = float(row[1])
        h = float(row[2])
        l = float(row[3])
        c = float(row[4])
        v = float(row[5])

        if any(x is None for x in [ts, o, h, l, c, v]):
            raise ValueError(f"Null value in Binance kline row {i}: {row}")

        candles.append([ts, o, h, l, c, v])

    return candles


def candles_to_dataframe(candles: list) -> pd.DataFrame:
    """Convert raw Binance kline list to a sorted DataFrame.

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
    """Write raw OHLCV DataFrame to S3 as Parquet."""
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    s3 = boto3.client("s3")
    s3.upload_fileobj(buf, bucket, key)
