"""
drift.py — Feature distribution drift detection using the Kolmogorov-Smirnov test.

The KS-test compares two empirical distributions (reference window vs recent window)
for each feature. Drift is declared only when 2 or more features drift simultaneously
(the 2-of-N gate), which reduces false positives on volatile crypto data.

Design decisions (from STATE.md):
- p-value threshold: 0.01 (not the 0.05 default) — tighter threshold for crypto volatility
- min_drifted gate: 2 — single-feature blips must not trigger retraining
- Minimum sample size: 30 non-null rows per feature — KS-test is unreliable below this
"""

import logging
from typing import List, Tuple

import pandas as pd
from scipy.stats import ks_2samp

logger = logging.getLogger(__name__)

# All 15 feature names — canonical list from src/features/compute.py FEATURE_COLS
FEATURE_NAMES = [
    "volatility_10m",
    "volatility_30m",
    "volatility_ratio",
    "rsi_14",
    "volume_spike",
    "volume_trend",
    "price_range_30m",
    "sma_10_vs_sma_30",
    "max_drawdown_30m",
    "candle_body_avg",
    "hour_of_day",
    "day_of_week",
    "fear_greed",
    "market_cap_change_24h",
    "btc_dominance",
]

_MIN_SAMPLES = 30  # Minimum non-null rows required to run KS-test on a feature


def compute_drift(
    reference_df: pd.DataFrame,
    recent_df: pd.DataFrame,
    features: List[str],
    p_threshold: float = 0.01,
    min_drifted: int = 2,
) -> Tuple[bool, float, List[str]]:
    """Detect feature distribution drift using the two-sample KS test.

    Compares the reference distribution (training-time feature statistics) against
    the recent distribution (last N predictions). Drift is flagged only when at least
    `min_drifted` features individually pass the KS-test significance threshold.

    Args:
        reference_df: DataFrame containing the reference feature window (e.g., training
            data loaded from S3 Parquet at features/reference/reference_features.parquet).
        recent_df: DataFrame containing the recent feature window (e.g., last 60 rows
            from Feast offline store or DynamoDB prediction log features field).
        features: List of feature column names to test. Must be present in both DataFrames.
        p_threshold: KS-test p-value threshold below which a feature is considered drifted.
            Default 0.01 (tighter than the 0.05 standard to reduce false positives on
            volatile BTC data).
        min_drifted: Minimum number of drifted features required to declare overall drift.
            Default 2 — the 2-of-N gate confirmed in STATE.md key decisions.

    Returns:
        Tuple of:
            - drift_detected (bool): True when len(drifted_features) >= min_drifted.
            - drift_score (float): Fraction of features drifted, in range [0.0, 1.0].
                Computed as len(drifted_features) / len(features).
            - drifted_features (list[str]): Names of features that individually drifted.

    Notes:
        - Features with fewer than 30 non-null samples in either window are skipped
          (KS-test is unreliable at low sample sizes). These are logged as warnings
          but are NOT counted as drifted features.
        - An empty features list returns (False, 0.0, []) without error.
    """
    if not features:
        return False, 0.0, []

    drifted: List[str] = []

    for feat in features:
        ref_vals = reference_df[feat].dropna().values if feat in reference_df.columns else []
        rec_vals = recent_df[feat].dropna().values if feat in recent_df.columns else []

        if len(ref_vals) < _MIN_SAMPLES or len(rec_vals) < _MIN_SAMPLES:
            logger.warning(
                "Skipping KS-test for feature '%s': insufficient non-null samples "
                "(reference=%d, recent=%d, min_required=%d)",
                feat,
                len(ref_vals),
                len(rec_vals),
                _MIN_SAMPLES,
            )
            continue

        stat, pvalue = ks_2samp(ref_vals, rec_vals)
        logger.debug("KS-test '%s': statistic=%.4f, p-value=%.6f", feat, stat, pvalue)

        if pvalue < p_threshold:
            drifted.append(feat)
            logger.info(
                "Drift detected in feature '%s': p-value=%.6f < threshold=%.2f",
                feat,
                pvalue,
                p_threshold,
            )

    drift_detected = len(drifted) >= min_drifted
    drift_score = len(drifted) / len(features)

    logger.info(
        "Drift summary: detected=%s, score=%.3f, drifted_features=%s",
        drift_detected,
        drift_score,
        drifted,
    )
    return drift_detected, drift_score, drifted
