"""
Main training script: Feast feature pull -> GridSearchCV -> ONNX export -> smoke test.

Usage:
    python -m training.train

Environment variables:
    FEAST_REPO_PATH   Path to Feast repo directory (default: feast/)
    S3_BUCKET         AWS S3 bucket name (used by Plan 03-02 S3 upload; read here for env parity)
    WANDB_API_KEY     Consumed by W&B (added in Plan 03-02)

Returns (via run_training()):
    (onnx_path: str, metrics: dict, best_params: dict)
"""

import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from xgboost import XGBClassifier

# ---------------------------------------------------------------------------
# ONNX converter registration — MUST happen at module level before any call
# to convert_sklearn. Missing this causes MissingConverter at conversion time.
# ---------------------------------------------------------------------------
from onnxmltools import convert_sklearn
from onnxmltools.utils import save_model as save_onnx_model
from onnxmltools.convert.xgboost.operator_converters.XGBoost import convert_xgboost
from skl2onnx import update_registered_converter
from skl2onnx.common.data_types import FloatTensorType

update_registered_converter(
    XGBClassifier,
    "XGBoostXGBClassifier",
    convert_xgboost,
    parser=None,
)

# ---------------------------------------------------------------------------
# Feature definitions — single source of truth
# Feature view name must match feast/features.py: "btc_volatility_features"
# Join key must match feast/features.py entity: "symbol"
# ---------------------------------------------------------------------------
FEATURE_NAMES = [
    "btc_volatility_features:volatility_10m",
    "btc_volatility_features:volatility_30m",
    "btc_volatility_features:volatility_ratio",
    "btc_volatility_features:rsi_14",
    "btc_volatility_features:volume_spike",
    "btc_volatility_features:volume_trend",
    "btc_volatility_features:price_range_30m",
    "btc_volatility_features:sma_10_vs_sma_30",
    "btc_volatility_features:max_drawdown_30m",
    "btc_volatility_features:candle_body_avg",
    "btc_volatility_features:hour_of_day",
    "btc_volatility_features:day_of_week",
]
FEATURE_COLS = [f.split(":")[1] for f in FEATURE_NAMES]  # strip view prefix

FEAST_REPO_PATH = os.environ.get("FEAST_REPO_PATH", "feast/")
S3_BUCKET = os.environ.get("S3_BUCKET", "")


def _load_features_from_feast() -> pd.DataFrame:
    """Pull point-in-time features from the Feast S3 offline store.

    Reads all Parquet files from the offline store to build an entity_df,
    then retrieves historical features via get_historical_features().

    The entity_df uses Feast's join key (symbol) and event_timestamp columns.
    The label column is included if present in the offline store Parquet files.

    Returns:
        DataFrame with FEATURE_COLS columns plus 'label' column, sorted by event_timestamp.
    """
    from feast import FeatureStore

    store = FeatureStore(repo_path=FEAST_REPO_PATH)

    # Retrieve the offline store Parquet path for btc_volatility_features
    # to build a valid entity_df from available timestamps.
    feature_view = store.get_feature_view("btc_volatility_features")
    data_source = feature_view.batch_source
    source_path = data_source.path  # s3://bucket/feast/offline/btc_features/

    # Read Parquet files from offline store to discover available timestamps
    import pyarrow.parquet as pq
    import pyarrow.dataset as ds

    try:
        dataset = ds.dataset(source_path, format="parquet")
        raw_df = dataset.to_table().to_pandas()
    except Exception as exc:
        raise RuntimeError(
            f"Failed to read Feast offline store at {source_path}: {exc}\n"
            "Ensure Phase 2 feature pipeline has run and S3 data is populated."
        ) from exc

    if raw_df.empty:
        raise RuntimeError(
            f"Feast offline store at {source_path} is empty. "
            "Run the Phase 2 feature pipeline to populate features before training."
        )

    # Build entity_df required by get_historical_features
    # Feast uses 'symbol' as the join key (from btc entity definition)
    entity_df = pd.DataFrame({
        "symbol": raw_df["symbol"].values,
        "event_timestamp": pd.to_datetime(raw_df["event_timestamp"], utc=True),
    })

    # Stash label if present in raw_df (written by store.py alongside features)
    label_map = None
    if "label" in raw_df.columns:
        label_map = dict(zip(
            pd.to_datetime(raw_df["event_timestamp"], utc=True).astype(str),
            raw_df["label"].values,
        ))

    # Pull historical features — this is the only feature source (no recomputation)
    feature_df = store.get_historical_features(
        entity_df=entity_df,
        features=FEATURE_NAMES,
    ).to_df()

    # Re-attach label from raw_df (get_historical_features strips non-feature columns)
    if label_map is not None:
        feature_df["label"] = (
            pd.to_datetime(feature_df["event_timestamp"], utc=True)
            .astype(str)
            .map(label_map)
        )
    elif "label" not in feature_df.columns:
        raise RuntimeError(
            "Label column not found in Feast offline store. "
            "Ensure write_to_feast_offline() included the 'label' column."
        )

    feature_df = feature_df.dropna(subset=FEATURE_COLS + ["label"])
    feature_df = feature_df.sort_values("event_timestamp").reset_index(drop=True)

    return feature_df


def run_training() -> tuple:
    """Execute full training pipeline: feature pull -> GridSearchCV -> ONNX export -> smoke test.

    Steps:
        1. Pull features from Feast offline store (no inline recomputation)
        2. Time-ordered train/test split (no shuffle — prevents look-ahead bias)
        3. GridSearchCV with TimeSeriesSplit (n_jobs=1 to avoid OOM on t3.micro)
        4. Evaluate on held-out test set
        5. Export best_estimator_ (NOT GridSearchCV wrapper) to ONNX
        6. Smoke test the exported ONNX (raises AssertionError on failure)
        7. Print metrics as JSON to stdout

    Returns:
        (onnx_path: str, metrics: dict, best_params: dict)

    Raises:
        AssertionError: If smoke test fails — prevents broken ONNX propagation.
        RuntimeError: If feature loading fails or feature count is unexpected.
    """
    # ------------------------------------------------------------------
    # 1. Load features from Feast offline store
    # ------------------------------------------------------------------
    df = _load_features_from_feast()

    # ------------------------------------------------------------------
    # 2. Time-ordered train/test split — NO shuffle (time series data)
    # ------------------------------------------------------------------
    cutoff = int(len(df) * 0.8)
    X_train = df[FEATURE_COLS].iloc[:cutoff].astype(np.float32)
    X_test = df[FEATURE_COLS].iloc[cutoff:].astype(np.float32)
    y_train = df["label"].iloc[:cutoff].astype(int)
    y_test = df["label"].iloc[cutoff:].astype(int)

    # ------------------------------------------------------------------
    # 3. GridSearchCV with TimeSeriesSplit
    #    n_jobs=1 on both GridSearchCV and XGBClassifier: CRITICAL to avoid
    #    OOM on t3.micro (1GB RAM). Do NOT change without profiling.
    # ------------------------------------------------------------------
    param_grid = {
        "max_depth": [3, 5, 7],
        "learning_rate": [0.01, 0.1, 0.3],
        "n_estimators": [50, 100, 200],
        "subsample": [0.8, 1.0],
    }
    tscv = TimeSeriesSplit(n_splits=5)
    clf = XGBClassifier(
        use_label_encoder=False,
        eval_metric="logloss",
        n_jobs=1,        # CRITICAL: avoid OOM on t3.micro
        random_state=42,
    )
    grid_search = GridSearchCV(
        clf,
        param_grid,
        cv=tscv,
        scoring="f1",
        n_jobs=1,        # outer loop also single-threaded
        verbose=1,
    )
    grid_search.fit(X_train, y_train)

    # ------------------------------------------------------------------
    # 4. Evaluate on held-out test set
    # ------------------------------------------------------------------
    y_pred = grid_search.predict(X_test)
    y_prob = grid_search.predict_proba(X_test)[:, 1]
    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "f1": float(f1_score(y_test, y_pred)),
        "roc_auc": float(roc_auc_score(y_test, y_prob)),
    }

    # ------------------------------------------------------------------
    # 5. ONNX export — export best_estimator_, NOT grid_search wrapper
    #    Exporting the wrapper silently produces a broken ONNX model.
    # ------------------------------------------------------------------
    n_features = X_train.shape[1]
    assert n_features == 12, f"Expected 12 features, got {n_features}"
    initial_type = [("X", FloatTensorType([None, n_features]))]

    onnx_model = convert_sklearn(
        grid_search.best_estimator_,   # NOT grid_search itself
        initial_types=initial_type,
        target_opset=15,
    )
    onnx_path = "/tmp/model.onnx"
    save_onnx_model(onnx_model, onnx_path)

    # ------------------------------------------------------------------
    # 6. Smoke test — must pass before returning artifact
    #    Raises AssertionError if model is broken; script exits non-zero.
    # ------------------------------------------------------------------
    from training.smoke_test import smoke_test_onnx

    smoke_test_onnx(onnx_path, n_features=12)

    return onnx_path, metrics, grid_search.best_params_


if __name__ == "__main__":
    try:
        onnx_path, metrics, best_params = run_training()
        print(json.dumps({"metrics": metrics, "best_params": best_params}, indent=2))
        print(f"Model saved to: {onnx_path}")
        sys.exit(0)
    except Exception as exc:
        print(f"Training failed: {exc}", file=sys.stderr)
        sys.exit(1)
