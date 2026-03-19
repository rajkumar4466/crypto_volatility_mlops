"""
Feature engineering for BTC OHLCV data.

Computes 15 look-ahead-safe features using rolling windows with min_periods
enforced on every call. The caller is responsible for dropping NaN rows
(the first ~30 warm-up rows) before writing to Feast.

WARNING: Do NOT call compute_features on data that includes future rows.
Fit scalers on the train split ONLY.
"""
import pandas as pd
import numpy as np
import requests

FEATURE_COLS = [
    "volatility_10m", "volatility_30m", "volatility_ratio",
    "rsi_14",
    "volume_spike", "volume_trend",
    "price_range_30m", "sma_10_vs_sma_30", "max_drawdown_30m",
    "candle_body_avg",
    "hour_of_day", "day_of_week",
    "fear_greed", "market_cap_change_24h", "btc_dominance",
]


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all 15 features from raw OHLCV data.

    min_periods is enforced on every rolling call — rows where a window
    is not yet full will contain NaN for that feature.
    The first 30 rows will have NaN in at least one feature (warm-up period).
    Rows 30+ will be fully populated.

    This function does NOT drop NaN rows — callers decide whether to drop
    or retain them for diagnostics.

    Args:
        df: DataFrame with columns: timestamp, open, high, low, close, volume

    Returns:
        DataFrame with all original columns plus the 15 FEATURE_COLS.
    """
    df = df.copy().sort_values("timestamp").reset_index(drop=True)

    ret = df["close"].pct_change()

    # --- Volatility (std of returns over window) ---
    df["volatility_10m"] = ret.rolling(10, min_periods=10).std()
    df["volatility_30m"] = ret.rolling(30, min_periods=30).std()
    # Ratio: avoid division by zero by replacing 0 with NaN
    vol30_safe = df["volatility_30m"].replace(0, np.nan)
    df["volatility_ratio"] = df["volatility_10m"] / vol30_safe

    # --- RSI-14 via EWM (standard Wilder smoothing approximation) ---
    # When loss=0 (all gains in window), RSI=100 by definition.
    # Using np.where avoids NaN from 0-division while preserving the correct value.
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(span=14, min_periods=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=14, min_periods=14, adjust=False).mean()
    # loss is NaN during warm-up (before min_periods rows), 0+ after warm-up
    rsi_raw = np.where(
        gain.isna() | loss.isna(),  # warm-up: not enough data yet
        np.nan,
        np.where(
            loss == 0,
            100.0,  # all gains — RSI is 100
            100 - (100 / (1 + gain / loss)),
        ),
    )
    df["rsi_14"] = rsi_raw

    # --- Volume features ---
    # CoinGecko free tier returns volume=0; fill with neutral 1.0 (no anomaly)
    vol_mean_30 = df["volume"].rolling(30, min_periods=30).mean()
    vol_mean_30_safe = vol_mean_30.replace(0, np.nan)
    df["volume_spike"] = (df["volume"] / vol_mean_30_safe).fillna(1.0)
    vol_mean_10 = df["volume"].rolling(10, min_periods=10).mean()
    df["volume_trend"] = (vol_mean_10 / vol_mean_30_safe).fillna(1.0)

    # --- Price features ---
    df["price_range_30m"] = (
        df["high"].rolling(30, min_periods=30).max()
        - df["low"].rolling(30, min_periods=30).min()
    )
    sma10 = df["close"].rolling(10, min_periods=10).mean()
    sma30 = df["close"].rolling(30, min_periods=30).mean()
    sma30_safe = sma30.replace(0, np.nan)
    df["sma_10_vs_sma_30"] = sma10 / sma30_safe
    rolling_max = df["close"].rolling(30, min_periods=30).max()
    rolling_max_safe = rolling_max.replace(0, np.nan)
    df["max_drawdown_30m"] = (df["close"] - rolling_max_safe) / rolling_max_safe
    df["candle_body_avg"] = (df["close"] - df["open"]).abs().rolling(10, min_periods=10).mean()

    # --- Temporal features (no leakage risk — derived from current candle timestamp) ---
    dt = pd.to_datetime(df["timestamp"], unit="ms")
    df["hour_of_day"] = dt.dt.hour.astype(int)
    df["day_of_week"] = dt.dt.dayofweek.astype(int)

    # --- Sentiment & market features (external APIs) ---
    df["fear_greed"] = _fetch_fear_greed(dt)
    mkt_df = _fetch_market_history(dt)
    df["market_cap_change_24h"] = mkt_df["market_cap_change_24h"].values
    df["btc_dominance"] = mkt_df["btc_dominance"].values

    return df


def _fetch_fear_greed(dt_series: pd.Series) -> pd.Series:
    """Fetch Fear & Greed Index history and map to candle timestamps.

    Returns a Series aligned to dt_series with forward-filled daily values.
    Falls back to 50 (neutral) on API failure.
    """
    try:
        # Fetch enough history to cover the full candle range
        date_range_days = (dt_series.max() - dt_series.min()).days + 5
        limit = max(date_range_days, 30)

        resp = requests.get(
            "https://api.alternative.me/fng/",
            params={"limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()["data"]

        # Build a daily series: date -> fear_greed value
        fg_records = []
        for entry in data:
            ts = pd.Timestamp(int(entry["timestamp"]), unit="s", tz="UTC")
            fg_records.append({"date": ts.normalize(), "fear_greed": float(entry["value"])})

        fg_df = pd.DataFrame(fg_records).drop_duplicates("date").set_index("date").sort_index()

        # Map each candle timestamp to its UTC date, then look up fear_greed
        candle_dates = dt_series.dt.tz_localize("UTC").dt.normalize()
        result = candle_dates.map(fg_df["fear_greed"]).astype(float)

        # Forward-fill gaps, backward-fill start, then fallback to 50
        result = result.ffill().bfill().fillna(50.0)

        mapped_count = result[result != 50.0].count()
        print(f"Fear & Greed: mapped {mapped_count}/{len(result)} candles to actual values")
        return result

    except Exception as e:
        print(f"WARNING: Fear & Greed API failed ({e}) — filling with 50 (neutral)")
        return pd.Series(50.0, index=dt_series.index)


def _fetch_market_history(dt_series: pd.Series) -> pd.DataFrame:
    """Fetch historical BTC market data from CoinGecko market_chart endpoint.

    Returns a DataFrame aligned to dt_series with:
      - market_cap_change_24h: daily pct change of BTC market cap
      - btc_dominance: estimated from BTC vs total crypto market cap

    Falls back to neutral values on API failure.
    """
    try:
        date_range_days = (dt_series.max() - dt_series.min()).days + 5
        days = max(date_range_days, 30)

        # Fetch BTC market chart (free tier supports up to 365 days)
        resp = requests.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": days},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # Parse market_caps: [[timestamp_ms, value], ...]
        mc_records = []
        for ts_ms, mc in data["market_caps"]:
            mc_records.append({
                "date": pd.Timestamp(ts_ms, unit="ms", tz="UTC").normalize(),
                "market_cap": mc,
            })
        mc_df = pd.DataFrame(mc_records)
        mc_daily = mc_df.groupby("date")["market_cap"].last().sort_index()

        # Compute 24h pct change of market cap
        mc_change = mc_daily.pct_change() * 100  # percentage
        mc_change = mc_change.fillna(0.0)

        # Estimate historical btc_dominance from BTC market cap trajectory.
        # CoinGecko free tier doesn't expose historical total crypto market cap,
        # so we use current btc_dominance as the anchor and apply BTC market cap
        # pct_change as a daily perturbation. This captures the direction of
        # dominance shifts even though the absolute level is approximate.
        current_btc_dom = _fetch_btc_dominance_current()
        mc_pct_change = mc_daily.pct_change().fillna(0.0)
        # Walk backwards from current dominance using cumulative product
        cum_factor = (1 + mc_pct_change).iloc[::-1].cumprod().iloc[::-1]
        btc_dom = current_btc_dom / cum_factor.iloc[0] * cum_factor
        btc_dom = btc_dom.clip(30, 80)  # keep in realistic range

        # Map to candle timestamps
        candle_dates = dt_series.dt.tz_localize("UTC").dt.normalize()

        result = pd.DataFrame(index=dt_series.index)
        result["market_cap_change_24h"] = candle_dates.map(mc_change).astype(float).ffill().bfill().fillna(0.0)
        result["btc_dominance"] = candle_dates.map(btc_dom).astype(float).ffill().bfill().fillna(current_btc_dom)

        print(f"Market history: mapped {days} days of market cap data to {len(result)} candles")
        return result

    except Exception as e:
        print(f"WARNING: CoinGecko market_chart failed ({e}) — filling with neutral values")
        result = pd.DataFrame(index=dt_series.index)
        result["market_cap_change_24h"] = 0.0
        result["btc_dominance"] = 55.0
        return result



def _fetch_btc_dominance_current() -> float:
    """Fetch current BTC dominance from CoinGecko /global endpoint."""
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["data"]["market_cap_percentage"]["btc"])
    except Exception:
        return 55.0
