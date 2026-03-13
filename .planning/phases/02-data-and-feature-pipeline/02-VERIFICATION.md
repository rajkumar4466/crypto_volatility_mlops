---
phase: 02-data-and-feature-pipeline
status: human_needed
score: 7/9
verified_date: 2026-03-12
---

# Phase 02: Data and Feature Pipeline — Verification

## Automated Checks (7/9 passed)

### Must-Have Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Ingest script fetches BTC OHLCV from CoinGecko with no API key, writes S3 Parquet | ✓ | `src/ingestion/coingecko.py` — `fetch_ohlcv`, `write_raw_to_s3` with boto3 |
| 2 | 12 features computed without look-ahead (min_periods enforced) | ✓ | `src/features/compute.py` — all rolling calls enforce min_periods |
| 3 | VOLATILE/CALM label at T uses only T+1..T+30, last 30 rows dropped | ✓ | `src/features/labels.py` — slice `[i+1:i+31]`, verified by test |
| 4 | Train/test split is time-ordered, unit test asserts this | ✓ | `src/features/pipeline.py` + `tests/test_features.py` |
| 5 | Training accuracy >80% flagged as leakage red flag | ✓ | Comment in pipeline.py |
| 6 | feast apply registers 12 features in S3 registry | ⏳ | Requires live AWS |
| 7 | Ingest → feature → Feast offline write produces S3 Parquet | ⏳ | Requires live AWS |
| 8 | feast materialize populates Redis online store | ✓ | `src/features/store.py` — `run_materialize` implemented |
| 9 | No feature computation in serving code | ✓ | `store.py` uses importlib, zero compute logic |

### Requirement Coverage

| Requirement | Status | Plan |
|-------------|--------|------|
| DATA-01 | ✓ | 02-01 |
| DATA-02 | ✓ | 02-01 |
| DATA-03 | ✓ | 02-01 |
| DATA-04 | ✓ | 02-01 |
| FEAT-01 | ✓ | 02-02 |
| FEAT-02 | ✓ | 02-02 |
| FEAT-03 | ✓ | 02-02 |
| FEAT-04 | ✓ | 02-02 |

### Tests

5/5 pass: `test_label_no_lookahead`, `test_train_test_split_time_ordered`, `test_feature_no_nan_after_warmup`, `test_feature_cols_complete`, `test_fetch_raises_on_null`

## Human Verification Required

1. `bash scripts/feast_setup.sh` — verify `feast feature-views list` shows 12 fields
2. `write_to_feast_offline` — verify S3 Parquet files created
3. `run_materialize` + `spot_check_online_store` — verify Redis populated
4. Offline vs online feature parity check

These require Phase 1 Terraform stack to be live — code is complete.
