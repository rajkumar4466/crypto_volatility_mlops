"""
Single source of truth for all Feast feature definitions.

CRITICAL: This file is imported by:
  - src/features/store.py (offline write path)
  - Training pipeline (reads offline features)
  - Serving Lambda (reads online features)

Never define feature names or types anywhere else.
Any change here MUST be followed by `feast apply`.

Import note: This file lives in the feast/ Feast repository directory. It is loaded
by store.py using importlib.util.spec_from_file_location (not as a Python package)
to avoid naming conflicts with the installed feast SDK package.
"""
from datetime import timedelta
from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32, Int32
import os

FEATURE_COLS = [
    "volatility_10m", "volatility_30m", "volatility_ratio",
    "rsi_14",
    "volume_spike", "volume_trend",
    "price_range_30m", "sma_10_vs_sma_30", "max_drawdown_30m",
    "candle_body_avg",
    "hour_of_day", "day_of_week",
    "fear_greed", "market_cap_change_24h", "btc_dominance",
]

S3_BUCKET = os.environ.get("FEAST_S3_BUCKET", "your-bucket-name")

# Entity — the identifier for our BTC prediction unit
btc = Entity(
    name="btc_symbol",
    description="BTC trading pair symbol (e.g., BTCUSDT)",
    join_keys=["symbol"],
)

# Offline store source — S3 Parquet files written by feature pipeline
btc_source = FileSource(
    path=f"s3://{S3_BUCKET}/feast/offline/btc_features/",
    timestamp_field="event_timestamp",
    created_timestamp_column="created_timestamp",
)

# Feature view — all 12 features with TTL = 2.5x the 30-min materialization interval
btc_features = FeatureView(
    name="btc_volatility_features",
    entities=[btc],
    ttl=timedelta(minutes=75),  # 2.5 x 30-min cycle. Prevents stale serving.
    schema=[
        Field(name="volatility_10m",   dtype=Float32),
        Field(name="volatility_30m",   dtype=Float32),
        Field(name="volatility_ratio", dtype=Float32),
        Field(name="rsi_14",           dtype=Float32),
        Field(name="volume_spike",     dtype=Float32),
        Field(name="volume_trend",     dtype=Float32),
        Field(name="price_range_30m",  dtype=Float32),
        Field(name="sma_10_vs_sma_30", dtype=Float32),
        Field(name="max_drawdown_30m", dtype=Float32),
        Field(name="candle_body_avg",  dtype=Float32),
        Field(name="hour_of_day",      dtype=Int32),
        Field(name="day_of_week",      dtype=Int32),
        Field(name="fear_greed",       dtype=Float32),
        Field(name="market_cap_change_24h", dtype=Float32),
        Field(name="btc_dominance",    dtype=Float32),
    ],
    source=btc_source,
    online=True,
)
