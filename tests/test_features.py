"""
Look-ahead bias guards and time-ordered split tests.

These tests are the ONLY automated protection against look-ahead bias
introduced during feature/label engineering. They must remain green
at all times. Any modification to compute.py or labels.py must keep
these tests passing.
"""
import pandas as pd
import numpy as np
import pytest

from src.features.compute import compute_features, FEATURE_COLS
from src.features.labels import label_volatility


def _make_ohlcv(n: int, start_price: float = 45000.0, freq_ms: int = 60_000) -> pd.DataFrame:
    """Generate a synthetic monotonically-increasing OHLCV DataFrame."""
    timestamps = [1_000_000 + i * freq_ms for i in range(n)]
    prices = [start_price + i * 10 for i in range(n)]
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": prices,
        "high": [p * 1.001 for p in prices],
        "low": [p * 0.999 for p in prices],
        "close": prices,
        "volume": [1000.0] * n,
    })


def test_label_no_lookahead():
    """
    Label at row T must use ONLY rows T+1..T+30.
    Guard: zeroing row 0 close price must NOT change row 0 label
    (because the label is computed from T+1 forward, not from T itself).
    After labeling a 60-row df, exactly 30 rows should remain (last 30 dropped).
    """
    df = _make_ohlcv(60)

    labeled = label_volatility(df)

    # Last 30 rows must be dropped
    assert len(labeled) == 30, (
        f"Expected 30 rows after dropping last 30, got {len(labeled)}"
    )

    # No NaN labels should remain after dropping
    assert labeled["label"].isna().sum() == 0, "NaN labels remain after dropna"

    # Zeroing row 0 close does NOT change its label (label uses forward window only)
    df_modified = df.copy()
    df_modified.loc[0, "close"] = 0.0
    labeled_modified = label_volatility(df_modified)

    assert labeled.iloc[0]["label"] == labeled_modified.iloc[0]["label"], (
        "Row 0 label changed when row 0 close was zeroed — "
        "look-ahead bias: label is using row T close in the window"
    )


def test_train_test_split_time_ordered():
    """
    Time-ordered 80/20 split must never mix timestamps.
    train.max(timestamp) < test.min(timestamp) — no shuffling allowed.
    """
    df = _make_ohlcv(100)

    # Time-ordered split at 80%
    cutoff = 80
    train = df.iloc[:cutoff]
    test = df.iloc[cutoff:]

    assert train["timestamp"].max() < test["timestamp"].min(), (
        "Train/test split is not time-ordered — timestamps overlap. "
        "Never shuffle time-series data before splitting."
    )


def test_feature_no_nan_after_warmup():
    """
    After the 30-row rolling warm-up, all 12 feature columns must be non-NaN.
    Rows 0..29 must have at least one NaN feature (confirms min_periods is enforced).
    """
    df = _make_ohlcv(60)
    featured = compute_features(df)

    # Rows 30+ must be fully populated
    post_warmup = featured.iloc[30:]
    nan_counts = post_warmup[FEATURE_COLS].isna().sum()
    assert nan_counts.sum() == 0, (
        f"NaN features found after warmup period:\n{nan_counts[nan_counts > 0]}"
    )

    # Rows 0..29 must have at least one NaN (warm-up not yet complete)
    pre_warmup = featured.iloc[:30]
    has_nan = pre_warmup[FEATURE_COLS].isna().any(axis=1)
    assert has_nan.any(), (
        "No NaN features in rows 0..29 — min_periods may not be enforced on "
        "all rolling windows. This could mask look-ahead bias."
    )


def test_feature_cols_complete():
    """
    FEATURE_COLS must contain exactly 12 named columns.
    This test documents the feature contract — any change here is intentional.
    """
    expected = [
        "volatility_10m", "volatility_30m", "volatility_ratio",
        "rsi_14",
        "volume_spike", "volume_trend",
        "price_range_30m", "sma_10_vs_sma_30", "max_drawdown_30m",
        "candle_body_avg",
        "hour_of_day", "day_of_week",
    ]
    assert len(FEATURE_COLS) == 12, f"Expected 12 features, got {len(FEATURE_COLS)}"
    assert FEATURE_COLS == expected, (
        f"FEATURE_COLS mismatch.\nExpected: {expected}\nGot: {FEATURE_COLS}"
    )
