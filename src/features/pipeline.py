"""
Feature engineering pipeline. Called by Feast store.py or Airflow task.
Produces labeled, feature-complete DataFrame ready for Feast offline write.

NOTE on look-ahead bias prevention:
- min_periods enforced on all rolling windows in compute.py
- Labels use T+1..T+30 forward window only (see labels.py)
- Split is by index cutoff — NEVER shuffle time series data
- Training accuracy > 80% on 288 samples likely indicates leakage — investigate
  (see must_haves in 02-01-PLAN.md for the 288-sample rationale)
"""
import pandas as pd

from src.features.compute import compute_features, FEATURE_COLS
from src.features.labels import label_volatility


def run_feature_pipeline(raw_df: pd.DataFrame) -> dict:
    """Run the full feature engineering and labeling pipeline.

    Input: raw OHLCV DataFrame from CoinGecko ingest (or replay).
    Output: dict with:
      - "full": complete labeled+featured df (used for Feast offline write)
      - "train": time-ordered training split (first 80%)
      - "test": time-ordered test split (last 20%)

    Steps:
      1. Compute 12 features (rolling windows with min_periods)
      2. Drop NaN rows from rolling warm-up (first ~30 rows)
      3. Apply VOLATILE/CALM labels (drops last 30 rows)
      4. Time-ordered 80/20 split by index cutoff — never shuffle

    Args:
        raw_df: DataFrame with columns: timestamp, open, high, low, close, volume

    Returns:
        dict with keys "full", "train", "test"

    Raises:
        AssertionError: if split results in empty train or test set,
                        or if train/test timestamps overlap
    """
    # Step 1: compute features
    featured_df = compute_features(raw_df)

    # Step 2: drop NaN rows from rolling warm-up (first ~30 rows)
    featured_df = featured_df.dropna(subset=FEATURE_COLS).reset_index(drop=True)

    # Step 3: apply VOLATILE/CALM labels (drops last 30 rows)
    labeled_df = label_volatility(featured_df)

    # Step 4: time-ordered split — NEVER shuffle time series
    cutoff = int(len(labeled_df) * 0.8)
    train_df = labeled_df.iloc[:cutoff].copy()
    test_df = labeled_df.iloc[cutoff:].copy()

    assert len(train_df) > 0 and len(test_df) > 0, (
        f"Insufficient data for train/test split. "
        f"total rows after labeling: {len(labeled_df)}, need at least 2"
    )
    assert train_df["timestamp"].max() < test_df["timestamp"].min(), (
        "Train/test split is NOT time-ordered — data contamination detected. "
        "This is a critical look-ahead bias bug."
    )

    return {
        "full": labeled_df,
        "train": train_df,
        "test": test_df,
    }
