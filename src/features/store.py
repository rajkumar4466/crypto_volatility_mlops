"""
Feast store integration. Writes computed features to the offline store (S3)
and materializes to the online store (Redis).

This is the ONLY path from computed features to storage.
Training reads from Feast offline. Serving reads from Feast online.
Neither path recomputes features.

Import note: feast/features.py is loaded via importlib.util.spec_from_file_location
to avoid naming conflicts between the local feast/ repository directory and the
installed feast SDK package. Never import it as `from feast.features import ...`.
"""
import os
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from feast import FeatureStore

REPO_PATH = os.environ.get("FEAST_REPO_PATH", "feast/")


def _load_feast_features():
    """
    Load feast/features.py using importlib to bypass the local feast/ directory
    that would otherwise shadow the installed feast SDK package.

    Returns the loaded module (access .FEATURE_COLS, .btc_features, etc.)
    """
    features_path = Path(REPO_PATH) / "features.py"
    spec = importlib.util.spec_from_file_location("feast_features", features_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_feast_entity_df(labeled_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add required Feast columns to the labeled feature DataFrame:
    - event_timestamp: datetime[UTC] from 'timestamp' column (ms since epoch)
    - created_timestamp: same as event_timestamp (Feast deduplication)
    - symbol: entity join key value

    labeled_df must have: timestamp (ms int), all 12 feature cols, label col.
    """
    df = labeled_df.copy()
    df["event_timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df["created_timestamp"] = df["event_timestamp"]
    df["symbol"] = "BTCUSDT"
    return df


def write_to_feast_offline(labeled_df: pd.DataFrame, store: FeatureStore = None) -> int:
    """
    Write labeled feature DataFrame to Feast offline store (S3 Parquet).
    Returns number of rows written.

    Call feast apply BEFORE this function on first run.
    On schema change: feast teardown -> feast apply -> re-run.
    """
    if store is None:
        store = FeatureStore(repo_path=REPO_PATH)

    feast_df = build_feast_entity_df(labeled_df)

    # Load FEATURE_COLS from feast/features.py via importlib (avoids package shadow)
    features_mod = _load_feast_features()
    FEATURE_COLS = features_mod.FEATURE_COLS

    # Select only Feast-required columns
    required_cols = ["symbol", "event_timestamp", "created_timestamp"] + FEATURE_COLS
    # Include label if present (for training use)
    if "label" in feast_df.columns:
        required_cols.append("label")
    feast_df = feast_df[[c for c in required_cols if c in feast_df.columns]]

    store.write_to_offline_store(
        feature_view_name="btc_volatility_features",
        df=feast_df,
    )
    print(f"Written {len(feast_df)} rows to Feast offline store (S3)")
    return len(feast_df)


def run_materialize(start_date: datetime = None, store: FeatureStore = None) -> None:
    """
    Materialize features from S3 offline store -> Redis online store.

    On first run: call with start_date = datetime of earliest feature row.
    On subsequent DAG runs: call without start_date (uses materialize_incremental).

    TTL on the feature view is 75 minutes (2.5x the 30-min cycle).
    Verify online store after materialization with get_online_features().
    """
    if store is None:
        store = FeatureStore(repo_path=REPO_PATH)

    end_date = datetime.now(timezone.utc)

    if start_date is not None:
        # Full materialization (first run or re-seed)
        print(f"Running full feast materialize from {start_date} to {end_date}")
        store.materialize(
            start_date=start_date,
            end_date=end_date,
        )
    else:
        # Incremental (DAG runs after first seed)
        print(f"Running feast materialize_incremental up to {end_date}")
        store.materialize_incremental(end_date=end_date)

    print("Materialization complete. Verify with: store.get_online_features()")


def spot_check_online_store(store: FeatureStore = None) -> dict:
    """
    Fetch one BTCUSDT feature row from Redis online store.
    Returns dict of feature name -> value. Values should be non-None if
    materialization ran successfully within the last 75 minutes.

    Use this after every materialize call to verify Redis is populated.
    """
    if store is None:
        store = FeatureStore(repo_path=REPO_PATH)

    # Load FEATURE_COLS from feast/features.py via importlib
    features_mod = _load_feast_features()
    FEATURE_COLS = features_mod.FEATURE_COLS

    feature_refs = [f"btc_volatility_features:{col}" for col in FEATURE_COLS]

    result = store.get_online_features(
        features=feature_refs,
        entity_rows=[{"symbol": "BTCUSDT"}],
    ).to_dict()

    null_count = sum(
        1 for v in result.values()
        if v is None or (isinstance(v, list) and v[0] is None)
    )
    if null_count > 0:
        print(
            f"WARNING: {null_count} null feature values in online store "
            f"-- TTL expired or materialization not run?"
        )
    else:
        print(f"Spot check PASS: all {len(FEATURE_COLS)} features non-null in Redis")

    return result
