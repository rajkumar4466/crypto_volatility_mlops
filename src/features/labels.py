"""
Volatility labeling for BTC OHLCV data.

Each row T is labeled VOLATILE or CALM based on the price swing
in the FUTURE 30-minute window: rows T+1 through T+30.

CRITICAL: Row T is NOT included in its own label's computation.
The last 30 rows are dropped because they have no complete forward window.

This module is the look-ahead bias gate for the entire pipeline.
Do NOT modify the slice boundaries without re-running the TDD tests in
tests/test_features.py::test_label_no_lookahead.
"""
import pandas as pd

SWING_THRESHOLD = 0.02  # >2% price swing in next 30 minutes = VOLATILE


def label_volatility(df: pd.DataFrame) -> pd.DataFrame:
    """Label each row as VOLATILE or CALM based on future 30-minute price swing.

    Label at row T = max |close[T+1..T+30] - close[T]| / close[T] > 2%

    CRITICAL: Label uses ONLY rows T+1 through T+30 (forward window).
    Row T itself is NOT included in the future window.
    Last 30 rows are dropped — they have no complete forward window.

    This function is the look-ahead bias gate. Do NOT change the slice
    from [i+1:i+31] to [i:i+30] — that would include row T itself,
    introducing look-ahead bias that is invisible until production.

    Args:
        df: DataFrame with columns: timestamp, close (and any feature columns)

    Returns:
        DataFrame with added "label" column (VOLATILE or CALM).
        Last 30 rows are dropped. Row count = len(df) - 30.
    """
    df = df.copy().sort_values("timestamp").reset_index(drop=True)
    n = len(df)
    labels = []

    for i in range(n):
        # Forward window: T+1 to T+30 (exclusive of T itself)
        # end = i+31 so slice [i+1:i+31] covers exactly T+1..T+30
        end = min(i + 31, n)
        if end - (i + 1) < 30:
            # Incomplete future window — last 30 rows
            labels.append(float("nan"))
            continue

        future_prices = df["close"].iloc[i + 1 : i + 31]
        current_price = df["close"].iloc[i]

        if current_price == 0:
            labels.append(float("nan"))
            continue

        swing = (future_prices.max() - future_prices.min()) / current_price
        labels.append("VOLATILE" if swing > SWING_THRESHOLD else "CALM")

    df["label"] = labels
    # Drop rows with incomplete forward window (last 30 rows)
    df = df.dropna(subset=["label"]).reset_index(drop=True)
    return df
