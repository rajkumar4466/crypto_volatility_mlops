"""
Feature engineering for BTC OHLCV data.

Computes 12 look-ahead-safe features using rolling windows with min_periods
enforced on every call. The caller is responsible for dropping NaN rows
(the first ~30 warm-up rows) before writing to Feast.

WARNING: Do NOT call compute_features on data that includes future rows.
Fit scalers on the train split ONLY.
"""
import pandas as pd
import numpy as np

FEATURE_COLS = [
    "volatility_10m", "volatility_30m", "volatility_ratio",
    "rsi_14",
    "volume_spike", "volume_trend",
    "price_range_30m", "sma_10_vs_sma_30", "max_drawdown_30m",
    "candle_body_avg",
    "hour_of_day", "day_of_week",
]


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all 12 features from raw OHLCV data.

    min_periods is enforced on every rolling call — rows where a window
    is not yet full will contain NaN for that feature.
    The first 30 rows will have NaN in at least one feature (warm-up period).
    Rows 30+ will be fully populated.

    This function does NOT drop NaN rows — callers decide whether to drop
    or retain them for diagnostics.

    Args:
        df: DataFrame with columns: timestamp, open, high, low, close, volume

    Returns:
        DataFrame with all original columns plus the 12 FEATURE_COLS.
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
    vol_mean_30 = df["volume"].rolling(30, min_periods=30).mean()
    vol_mean_30_safe = vol_mean_30.replace(0, np.nan)
    df["volume_spike"] = df["volume"] / vol_mean_30_safe
    vol_mean_10 = df["volume"].rolling(10, min_periods=10).mean()
    df["volume_trend"] = vol_mean_10 / vol_mean_30_safe

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

    return df
