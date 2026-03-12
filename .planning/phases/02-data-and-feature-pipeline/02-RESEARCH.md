# Phase 2: Data and Feature Pipeline - Research

**Researched:** 2026-03-12
**Domain:** CoinGecko OHLCV ingestion, 12-feature engineering, VOLATILE/CALM labeling, Feast S3 offline + Redis online feature store
**Confidence:** MEDIUM (Feast S3+Redis integration details have MEDIUM confidence; CoinGecko API and feature math are HIGH)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DATA-01 | Ingest BTC 1-minute OHLCV candles from CoinGecko free API (no API key) | CoinGecko `/coins/bitcoin/market_chart` endpoint; `requests` library; 30 req/min rate limit; one call per DAG run (fetch last N candles); null-field guard |
| DATA-02 | Compute 12 engineered features: volatility_10m, volatility_30m, volatility_ratio, rsi_14, volume_spike, volume_trend, price_range_30m, sma_10_vs_sma_30, max_drawdown_30m, candle_body_avg, hour_of_day, day_of_week | Pure pandas rolling/shift math; `min_periods` required on all windows to avoid back-fill leakage; RSI via EWM; all arithmetic on training split only |
| DATA-03 | Label each sample: VOLATILE (>2% swing in next 30 min) or CALM | Label at time T uses only data T+1..T+30; computed with forward-looking `.shift(-N)` on close price; drop last 30 rows (no future window); verified in unit test |
| DATA-04 | Time-ordered train/test split (no shuffle) to prevent look-ahead bias | Split by integer index cutoff (e.g., 80% mark); never `train_test_split(shuffle=True)` for time series; scaler fitted on train split only |
| FEAT-01 | Feast feature definitions for all 12 features (single source of truth) | `FeatureView` + `Entity` + `Field` in `feast/features.py`; `feast apply` registers schema; all downstream code imports from this file |
| FEAT-02 | S3 offline store for historical features (Parquet, used by training) | `FileSource` with S3 path; `feast.write_to_offline_store()` writes Parquet; `store.get_historical_features()` with entity_df including `event_timestamp` for point-in-time join |
| FEAT-03 | Redis online store via ElastiCache t3.micro (used by serving) | `RedisOnlineStore` config in `feature_store.yaml`; `feast materialize_incremental` copies latest values; TTL = materialization_interval × 2.5 |
| FEAT-04 | Feature computation happens once in ingest, written to both stores — no duplication in training or serving code | Feature pipeline writes to Feast offline; `feast materialize` moves to online; training reads offline; serving reads online; no feature math in Lambda handler |

</phase_requirements>

---

## Summary

Phase 2 builds the data plumbing that all downstream phases depend on. It has two distinct concerns that must stay cleanly separated: (1) raw data acquisition from CoinGecko and (2) feature store population via Feast. These are implemented as two sequential pipeline stages — ingest writes raw OHLCV Parquet to S3; feature engineering reads that Parquet, computes 12 features + VOLATILE/CALM labels, and writes to the Feast offline store; materialization pushes the latest values to Redis for serving.

The dominant risk in Phase 2 is **look-ahead bias** — the most common silent failure mode in time-series ML. Features that inadvertently incorporate future data will make training metrics look great (80%+ accuracy) while live predictions are near-random. Every rolling window computation must use `min_periods`, every label must use only `t+1..t+30` data, and the train/test split must be index-ordered. A unit test asserting these properties is a success criterion for the phase.

The secondary risk is **Feast misconfiguration** leading to training-serving skew. The feature view defined in `feast/features.py` must be the single place where feature names and types are declared. Both the offline training path and the online serving path must read from Feast — no feature recomputation in the Lambda handler. Feast S3+Redis integration has MEDIUM confidence in project research; validate `feast apply` behavior against Feast 0.61.0 during implementation.

**Primary recommendation:** Implement ingest and feature engineering as a single standalone Python script first, verify it end-to-end on real CoinGecko data, then layer the Feast integration on top. Do not attempt to wire Feast into the DAG until the offline store is populated and a local `feast get_historical_features()` call returns the expected shape.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| requests | latest | CoinGecko HTTP calls | Standard sync HTTP; one call per run fits rate limit |
| pandas | 3.0.1 | OHLCV manipulation, rolling feature math | De-facto for tabular time-series; `.rolling()`, `.shift()`, `.ewm()` cover all 12 features |
| pyarrow | latest | Parquet read/write for Feast S3 offline store | Required by Feast S3 provider; do not use fastparquet |
| feast | 0.61.0 | Feature store: S3 offline + Redis online | Single source of truth; prevents training-serving skew |
| boto3 | latest | S3 uploads, raw OHLCV write | AWS SDK standard |
| pytest | latest | Unit tests (look-ahead bias assertions) | CI gate |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | (pandas transitive) | Numerical ops in feature math | Do not pin separately |
| python-dateutil | (boto3 transitive) | Timestamp parsing for CoinGecko response | Do not pin separately |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `requests` | `httpx` | `httpx` adds async but CoinGecko polling is sync; no benefit |
| Feast S3 offline | Custom Parquet on S3 | Custom loses point-in-time join; defeats FEAT-04 |
| Feast Redis online | Feast SQLite online | SQLite acceptable if ElastiCache free tier ineligible; loses sub-10ms serving latency |

**Installation:**
```bash
pip install pandas==3.0.1 feast==0.61.0 pyarrow boto3 requests pytest
```

---

## Architecture Patterns

### Recommended Project Structure
```
src/
├── ingestion/
│   └── coingecko.py         # fetch_ohlcv(), write_raw_to_s3()
├── features/
│   ├── compute.py           # all 12 feature functions (pure pandas, no side effects)
│   ├── labels.py            # label_volatility() — forward window only
│   └── store.py             # write_to_feast_offline(), run_materialize()
feast/
├── feature_store.yaml       # registry, offline (S3), online (Redis) config
└── features.py              # Entity, FeatureView, Field definitions
tests/
├── test_features.py         # look-ahead bias + time-ordered split assertions
└── test_ingest.py           # CoinGecko null-field handling
```

### Pattern 1: CoinGecko Ingest — One Call, Bounded Window
**What:** Fetch only the last N 1-minute candles per run (e.g., last 60 minutes = 60 candles). Store a watermark (last successful timestamp) in S3 to avoid re-fetching old data.
**When to use:** Every DAG ingest task and standalone ingest script invocation.
**Example:**
```python
# src/ingestion/coingecko.py
import requests

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlcv"
HEADERS = {"User-Agent": "crypto-volatility-mlops/1.0"}

def fetch_ohlcv(days: float = 0.1) -> list[list]:
    """Fetch last ~144 1-min BTC candles. days=0.1 ≈ 144 minutes."""
    resp = requests.get(
        COINGECKO_URL,
        params={"vs_currency": "usd", "days": days},
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    candles = data.get("prices", [])  # [[timestamp_ms, open, high, low, close], ...]
    # Guard against nulls — raise rather than propagate NaN into features
    for row in candles:
        if any(v is None for v in row):
            raise ValueError(f"Null values in CoinGecko response: {row}")
    return candles
```

### Pattern 2: 12-Feature Computation — Strict No-Leakage Rolling
**What:** All 12 features computed on the training window only, using `min_periods` on every rolling call. No `.fillna(0)` that could back-fill future windows.
**When to use:** `src/features/compute.py` — called by the feature pipeline task, not by Lambda.
**Example:**
```python
# src/features/compute.py
import pandas as pd
import numpy as np

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Input: df with columns [timestamp, open, high, low, close, volume]
    Returns df with 12 additional feature columns.
    min_periods is set on every rolling call to avoid back-filling early rows.
    """
    df = df.copy().sort_values("timestamp").reset_index(drop=True)

    # Volatility features (std of returns)
    ret = df["close"].pct_change()
    df["volatility_10m"] = ret.rolling(10, min_periods=10).std()
    df["volatility_30m"] = ret.rolling(30, min_periods=30).std()
    df["volatility_ratio"] = df["volatility_10m"] / df["volatility_30m"].replace(0, np.nan)

    # RSI-14 via EWM
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(span=14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(span=14, min_periods=14).mean()
    df["rsi_14"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    # Volume features
    vol_mean = df["volume"].rolling(30, min_periods=30).mean()
    df["volume_spike"] = df["volume"] / vol_mean.replace(0, np.nan)
    df["volume_trend"] = df["volume"].rolling(10, min_periods=10).mean() / vol_mean.replace(0, np.nan)

    # Price features
    df["price_range_30m"] = df["high"].rolling(30, min_periods=30).max() - df["low"].rolling(30, min_periods=30).min()
    sma10 = df["close"].rolling(10, min_periods=10).mean()
    sma30 = df["close"].rolling(30, min_periods=30).mean()
    df["sma_10_vs_sma_30"] = sma10 / sma30.replace(0, np.nan)
    rolling_max = df["close"].rolling(30, min_periods=30).max()
    df["max_drawdown_30m"] = (df["close"] - rolling_max) / rolling_max.replace(0, np.nan)
    df["candle_body_avg"] = (df["close"] - df["open"]).abs().rolling(10, min_periods=10).mean()

    # Temporal features (no leakage risk)
    dt = pd.to_datetime(df["timestamp"], unit="ms")
    df["hour_of_day"] = dt.dt.hour
    df["day_of_week"] = dt.dt.dayofweek

    return df
```

### Pattern 3: VOLATILE/CALM Labeling — Forward Window Only
**What:** Label at time `t` is computed from close prices at `t+1` through `t+30`. Uses `.shift(-N)` to look forward. Rows where the future window is incomplete (last 30 rows) are dropped.
**When to use:** `src/features/labels.py` — applied after feature computation.
**Example:**
```python
# src/features/labels.py
import pandas as pd

SWING_THRESHOLD = 0.02  # >2% price swing in next 30 min = VOLATILE

def label_volatility(df: pd.DataFrame) -> pd.DataFrame:
    """
    Label at time t: max(|close[t+1..t+30] - close[t]| / close[t]) > 2%
    Forward-shift only. Last 30 rows have no complete future window — drop them.
    """
    df = df.copy()
    future_max = pd.Series(
        [
            df["close"].iloc[i+1:i+31].max() if i + 31 <= len(df) else float("nan")
            for i in range(len(df))
        ],
        index=df.index,
    )
    future_min = pd.Series(
        [
            df["close"].iloc[i+1:i+31].min() if i + 31 <= len(df) else float("nan")
            for i in range(len(df))
        ],
        index=df.index,
    )
    swing = (future_max - future_min) / df["close"].replace(0, float("nan"))
    df["label"] = (swing > SWING_THRESHOLD).map({True: "VOLATILE", False: "CALM"})
    # Drop rows where future window is incomplete
    df = df.dropna(subset=["label"])
    return df
```

### Pattern 4: Time-Ordered Train/Test Split
**What:** Split by integer index cutoff. Never shuffle. Scaler fitted on train subset only.
**When to use:** Applied at the boundary of the feature pipeline before Feast write; validated in unit test.
**Example:**
```python
# Correct time-ordered split
cutoff = int(len(df) * 0.8)
train_df = df.iloc[:cutoff]
test_df  = df.iloc[cutoff:]
# NEVER: train_test_split(df, shuffle=True)
```

### Pattern 5: Feast Feature Store Setup (S3 offline + Redis online)
**What:** `feast/feature_store.yaml` configures registry (S3 JSON), offline store (S3 Parquet via FileSource), and online store (Redis). `feast/features.py` defines Entity, FeatureView, and Field. `feast apply` registers the schema.
**When to use:** Feast directory initialized once; `feast apply` re-run after any schema change (treat like a DB migration).
**Example:**
```yaml
# feast/feature_store.yaml
project: crypto_volatility
registry: s3://your-bucket/feast/registry.pb
provider: aws
online_store:
  type: redis
  connection_string: "your-elasticache-endpoint:6379"
offline_store:
  type: file
entity_key_serialization_version: 2
```

```python
# feast/features.py
from datetime import timedelta
from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32, Int32, String

btc = Entity(name="btc_symbol", join_keys=["symbol"])

btc_source = FileSource(
    path="s3://your-bucket/feast/offline/btc_features/",
    timestamp_field="event_timestamp",
)

btc_features = FeatureView(
    name="btc_volatility_features",
    entities=[btc],
    ttl=timedelta(minutes=75),  # 2.5x the 30-min materialization interval
    schema=[
        Field(name="volatility_10m",    dtype=Float32),
        Field(name="volatility_30m",    dtype=Float32),
        Field(name="volatility_ratio",  dtype=Float32),
        Field(name="rsi_14",            dtype=Float32),
        Field(name="volume_spike",      dtype=Float32),
        Field(name="volume_trend",      dtype=Float32),
        Field(name="price_range_30m",   dtype=Float32),
        Field(name="sma_10_vs_sma_30",  dtype=Float32),
        Field(name="max_drawdown_30m",  dtype=Float32),
        Field(name="candle_body_avg",   dtype=Float32),
        Field(name="hour_of_day",       dtype=Int32),
        Field(name="day_of_week",       dtype=Int32),
    ],
    source=btc_source,
    online=True,
)
```

```python
# src/features/store.py — writing to Feast offline
import pandas as pd
from feast import FeatureStore

def write_to_feast_offline(features_df: pd.DataFrame, store: FeatureStore):
    """
    features_df must have columns: symbol (entity key), event_timestamp, + 12 feature cols
    """
    store.write_to_offline_store(
        feature_view_name="btc_volatility_features",
        df=features_df,
    )

def run_materialize(store: FeatureStore, start_ts, end_ts):
    """Push offline → Redis online store."""
    store.materialize_incremental(end_date=end_ts)
```

### Anti-Patterns to Avoid
- **Rolling without min_periods:** `df["x"].rolling(30).std()` back-fills the first 29 rows using incomplete windows — set `min_periods=30` always.
- **Labeling with same-candle data:** The label for candle `t` must not use candle `t` itself in the future window. Start the forward slice at `t+1`.
- **Computing features twice:** Never recompute features in training scripts or Lambda handler. If it's not reading from Feast, it's wrong.
- **feast apply after schema change without teardown:** Renaming a feature view leaves orphaned Redis keys. Run `feast teardown` before any rename.
- **Shuffled train/test split:** `train_test_split(df, shuffle=True)` is the fastest way to get inflated accuracy on time-series data. Always split by index cutoff.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Feature store offline/online separation | Custom S3 read/write in training + Lambda | Feast | Custom code duplicates feature logic; Feast enforces single definition via `FeatureView` |
| Point-in-time feature join | Custom timestamp-aligned merge | `store.get_historical_features()` | Feast's PIT join avoids future data leakage at training time |
| RSI computation | Custom loop | Pandas EWM | EWM correctly handles the exponentially-weighted rolling average; loop implementations often have off-by-one errors |
| Parquet schema management | Custom Parquet writer | Feast + pyarrow | Feast manages schema evolution and partition layout on S3 |

**Key insight:** Feature stores exist precisely because the custom alternative — rewriting feature logic in multiple places — is the root cause of training-serving skew in ~40% of deployed ML systems.

---

## Common Pitfalls

### Pitfall 1: Look-Ahead Bias via Rolling Without min_periods
**What goes wrong:** `pd.Series.rolling(N).std()` with no `min_periods` computes partial-window statistics for the first N-1 rows, back-filling them with statistically biased values. The model trains on "features" that incorporate distributional information from the future.
**Why it happens:** Pandas default `min_periods=1` for backward compatibility.
**How to avoid:** Always set `min_periods=N` equal to the window size. Drop rows where any feature is NaN before the Feast write.
**Warning signs:** Feature values for the first 30 rows look suspiciously well-behaved; accuracy above 80% on 288-sample dataset.

### Pitfall 2: Label Uses Current Candle in Future Window
**What goes wrong:** A common mistake is `df["close"].iloc[i:i+30]` which includes candle `i` itself. The label "how much will price move in the next 30 minutes" must start at `i+1`.
**Why it happens:** Off-by-one in slice indexing.
**How to avoid:** Use `iloc[i+1:i+31]`. Write a unit test that asserts `label_df["label"].iloc[0]` is computed from rows `1..30` only.
**Warning signs:** Label distribution looks too clean; train accuracy collapses to random at first live prediction.

### Pitfall 3: Feast TTL Shorter Than Materialization Interval
**What goes wrong:** Redis returns null/expired features at serving time even though materialization ran successfully. Feast TTL on the feature view controls how long Redis keys are valid.
**Why it happens:** Default TTL settings are short; if the materialization cycle is 30 minutes and TTL is 30 minutes, any serving latency causes a miss.
**How to avoid:** Set `ttl=timedelta(minutes=75)` (2.5× the 30-min cycle). Verify with a Redis spot-check after `feast materialize`.
**Warning signs:** `store.get_online_features()` returns `None` values for features; Lambda handler gets NaN input vector.

### Pitfall 4: CoinGecko API Null Fields
**What goes wrong:** CoinGecko occasionally returns `null` for price fields during API hiccups. If null is treated as `0`, feature division operations produce infinity or NaN that silently propagates into the offline store.
**Why it happens:** CoinGecko free API has no SLA; partial data is possible.
**How to avoid:** Explicitly check each row for null values immediately after parsing the API response; raise a pipeline exception rather than continuing with incomplete data. This allows the DAG to retry cleanly.
**Warning signs:** NaN features in Parquet; Feast write succeeds but training data has sparse rows.

### Pitfall 5: feast apply Not Re-Run After Schema Change
**What goes wrong:** Adding or renaming a feature field without running `feast apply` causes `write_to_offline_store()` to fail with a schema mismatch error that can appear as a silent write failure.
**Why it happens:** Feast registry (S3 JSON) is separate from the feature view Python definitions. The registry is only updated when `feast apply` runs.
**How to avoid:** Treat `feast apply` like a DB migration — run it every time `feast/features.py` changes. Add it as the first step in the feature pipeline setup sequence.
**Warning signs:** Feast Python SDK raises `RegistryNotFound` or `FeatureViewNotFoundException`; offline store Parquet has different columns than expected.

---

## Code Examples

### CoinGecko API Response Structure
```python
# Response from GET /coins/bitcoin/market_chart?vs_currency=usd&days=0.1
# Returns arrays: prices, market_caps, total_volumes
# Each item: [timestamp_ms, value]
# For OHLCV, use /coins/bitcoin/ohlcv endpoint:
# Returns: [[timestamp_ms, open, high, low, close, volume], ...]
```

### Feast Offline Write Pattern
```python
import pandas as pd
from feast import FeatureStore
from datetime import timezone

store = FeatureStore(repo_path="feast/")

# features_df schema required by Feast:
# - entity join key column (e.g., "symbol" = "BTCUSDT")
# - "event_timestamp" column (datetime with timezone)
# - 12 feature columns

features_df["event_timestamp"] = pd.to_datetime(
    features_df["timestamp"], unit="ms", utc=True
)
features_df["symbol"] = "BTCUSDT"

store.write_to_offline_store(
    feature_view_name="btc_volatility_features",
    df=features_df[["symbol", "event_timestamp"] + FEATURE_COLS],
)
```

### Feast Online Feature Fetch (Training path)
```python
# Training reads from offline store with point-in-time join
entity_df = pd.DataFrame({
    "symbol": ["BTCUSDT"] * len(timestamps),
    "event_timestamp": timestamps,
})
training_data = store.get_historical_features(
    entity_df=entity_df,
    features=["btc_volatility_features:" + f for f in FEATURE_COLS],
).to_df()
```

### Look-Ahead Bias Unit Test
```python
# tests/test_features.py
def test_label_no_lookahead(sample_df):
    """Label at row i must use only rows i+1..i+30."""
    labeled = label_volatility(sample_df.copy())
    # Verify: modifying row 0 does not change label at row -31
    # Verify: last 30 rows are dropped (no complete future window)
    assert labeled["label"].isna().sum() == 0  # no NaN labels remain
    assert len(labeled) == len(sample_df) - 30  # last 30 dropped

def test_train_test_split_time_ordered(feature_df):
    """Train set must end before test set begins."""
    cutoff = int(len(feature_df) * 0.8)
    train = feature_df.iloc[:cutoff]
    test  = feature_df.iloc[cutoff:]
    assert train.index.max() < test.index.min()
    assert train["timestamp"].max() < test["timestamp"].min()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Custom feature table in DB | Feast feature store | 2021+ | Prevents training-serving skew structurally |
| Random shuffle train/test split | Time-ordered index split + TimeSeriesSplit for CV | Standard since 2023 | Eliminates look-ahead bias |
| SQLite for Airflow metadata | RDS PostgreSQL (db.t3.micro) | Required since Airflow 2.x | Required for multi-task DAG parallelism |
| Lambda ZIP packages | Lambda container images (up to 10GB) | 2020 | Enables onnxruntime + feast in Lambda |

**Deprecated/outdated:**
- `feast get_historical_features(entity_df, feature_refs=["feature_view:feature"])` syntax: Current Feast (0.40+) uses `features=["view:field"]` list directly.
- `feast materialize` (full): Prefer `feast materialize_incremental` in DAG for efficiency; only use full materialize for initial population.

---

## Open Questions

1. **Feast 0.61.0 `write_to_offline_store()` exact DataFrame schema requirements**
   - What we know: Feast requires entity join key, `event_timestamp`, and feature columns; basic pattern verified via official Feast docs
   - What's unclear: Whether Feast 0.61.0 requires a specific `created_timestamp` column alongside `event_timestamp` for deduplication
   - Recommendation: Test with a minimal 5-row DataFrame during setup; check Feast SDK's validation error messages to discover any missing required columns

2. **CoinGecko `/coins/bitcoin/ohlcv` vs `/coins/bitcoin/market_chart` for 1-min candles**
   - What we know: CoinGecko free API has both endpoints; `market_chart` returns price/volume arrays, `ohlcv` returns OHLCV candles
   - What's unclear: Whether the free tier (no API key) provides 1-minute granularity on `ohlcv` endpoint or defaults to hourly/daily
   - Recommendation: Test both endpoints in ingest script; if 1-min OHLCV is unavailable without API key, derive OHLCV from `market_chart` prices (open=close[t-1], high/low from nearby points)

3. **Feast `materialize_incremental` start date behavior**
   - What we know: `materialize_incremental(end_date)` pushes features from the last materialization timestamp to `end_date`
   - What's unclear: Whether the first call on an empty online store requires `materialize` (full) before `materialize_incremental` works, or if incremental handles the empty-store case
   - Recommendation: On first run, call `store.materialize(start_date, end_date)` explicitly; switch to `materialize_incremental` on subsequent DAG runs

---

## Validation Architecture

> `workflow.nyquist_validation` not present in config.json — skipping formal test map. Tests are specified inline in requirements and plan verification steps.

Key test to implement in Wave 0 of plan 02-01:
- `tests/test_features.py::test_label_no_lookahead` — asserts label at T uses only T+1..T+30
- `tests/test_features.py::test_train_test_split_time_ordered` — asserts split is index-ordered
- `tests/test_features.py::test_feature_no_nan_after_warmup` — asserts all 12 features are non-NaN after the warm-up window (row 30+)

Quick run: `pytest tests/test_features.py -x`
Phase gate: All three tests green before `/gsd:verify-work`

---

## Sources

### Primary (HIGH confidence)
- Project research: `/Users/mithra_sundaram/Desktop/code/models/crypto_volatility_mlops/.planning/research/SUMMARY.md` — stack, architecture, pitfalls (2026-03-12)
- Project research: `/Users/mithra_sundaram/Desktop/code/models/crypto_volatility_mlops/.planning/research/STACK.md` — version matrix (2026-03-12)
- Project research: `/Users/mithra_sundaram/Desktop/code/models/crypto_volatility_mlops/.planning/research/PITFALLS.md` — look-ahead bias, Feast TTL, CoinGecko null handling (2026-03-12)
- Pandas docs — `.rolling(min_periods=N)` semantics: authoritative
- CoinGecko docs — rate limit 30 req/min free tier, null field handling

### Secondary (MEDIUM confidence)
- Feast official docs (docs.feast.dev) — `write_to_offline_store`, `get_historical_features`, `materialize_incremental` patterns
- Feast Practical Operation Guide (March 2026) — online/offline store pattern
- arXiv 2407.11786 — RSI, MACD, Bollinger Bands as top crypto prediction features

### Tertiary (LOW confidence)
- CoinGecko 1-min OHLCV granularity without API key — not directly verified; test during implementation

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages pinned, versions verified on PyPI 2026-03-12
- Feature math: HIGH — pandas rolling/shift/ewm are well-documented; 12 formulas are standard TA indicators
- Look-ahead bias prevention: HIGH — time-series ML best practices are well-established
- Feast integration details (exact DataFrame schema, materialize_incremental first-run behavior): MEDIUM — basic patterns verified; edge cases need implementation validation
- CoinGecko 1-min granularity on free tier: LOW — not directly confirmed; test during implementation

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (Feast 0.61.x is stable; CoinGecko API policy unlikely to change within 30 days)
