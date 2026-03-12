---
phase: 02-data-and-feature-pipeline
plan: 01
subsystem: data-pipeline
tags: [coingecko, pandas, numpy, boto3, pytest, parquet, s3, features, labels, tdd]

# Dependency graph
requires:
  - phase: 01-infrastructure-foundation
    provides: S3 bucket, IAM roles, Terraform infrastructure for data storage

provides:
  - CoinGecko OHLCV ingest (fetch_ohlcv, candles_to_dataframe, write_raw_to_s3)
  - 12 look-ahead-safe feature columns (compute_features, FEATURE_COLS)
  - VOLATILE/CALM labels using T+1..T+30 forward window only (label_volatility)
  - Time-ordered 80/20 train/test pipeline (run_feature_pipeline)
  - TDD test suite guarding against look-ahead bias and null propagation
affects:
  - 02-02 (Feast feature store depends on labeled DataFrame schema)
  - 03-training (depends on train/test splits from run_feature_pipeline)
  - 04-serving (depends on FEATURE_COLS contract for inference input)
  - 06-drift (depends on feature column names for KS-test monitoring)

# Tech tracking
tech-stack:
  added: [pandas, numpy, boto3, pyarrow, requests, pytest]
  patterns:
    - min_periods enforced on every rolling window call to prevent early NaN leakage
    - Forward-only labeling window (T+1..T+30) with last-N-rows drop
    - np.where(loss==0, 100) for RSI edge case instead of replace(0, nan)
    - Time-ordered split by index cutoff — no shuffle for time series
    - TDD RED/GREEN for look-ahead bias guards (tests written before implementation)

key-files:
  created:
    - src/ingestion/coingecko.py
    - src/ingestion/ingest.py
    - src/features/compute.py
    - src/features/labels.py
    - src/features/pipeline.py
    - tests/test_features.py
    - tests/test_ingest.py
  modified: []

key-decisions:
  - "RSI uses np.where(loss==0, 100) not replace(0, nan) — monotonic price sequences produce zero loss; NaN RSI would propagate to Feast and corrupt features"
  - "label_volatility uses slice [i+1:i+31] not [i:i+30] — includes only T+1..T+30, never row T itself; function comment explicitly documents this as the look-ahead bias gate"
  - "compute_features does not drop NaN rows — caller decides whether to drop or keep for diagnostics; pipeline.py drops via dropna(subset=FEATURE_COLS)"
  - "SWING_THRESHOLD = 0.02 (2%) — per RESEARCH.md, 2% swing in 30 min is the VOLATILE/CALM boundary for BTC 1-min data"

patterns-established:
  - "Feature contract: FEATURE_COLS list in compute.py is the single source of truth — downstream (Feast, Lambda, drift monitor) must import this list, never hardcode"
  - "Look-ahead bias gate: test_label_no_lookahead zeroes row T close and asserts label is unchanged — this test must remain green on any labels.py modification"
  - "Time-series split: always use index cutoff (iloc[:cutoff]), assert train.max < test.min — never shuffle"

requirements-completed: [DATA-01, DATA-02, DATA-03, DATA-04]

# Metrics
duration: 6min
completed: 2026-03-12
---

# Phase 2 Plan 1: Data and Feature Pipeline Summary

**CoinGecko OHLCV ingest → 12 rolling features with min_periods enforced → forward-window VOLATILE/CALM labels (T+1..T+30), TDD-verified look-ahead bias guards, and time-ordered 80/20 pipeline**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-03-12T22:36:37Z
- **Completed:** 2026-03-12T22:42:10Z
- **Tasks:** 3 (RED, GREEN, pipeline entrypoint)
- **Files modified:** 10

## Accomplishments

- Three production modules ship: coingecko.py (ingest), compute.py (12 features), labels.py (VOLATILE/CALM labels) — all with null guards and look-ahead bias prevention
- Five TDD tests guard against look-ahead bias, null propagation, feature warm-up correctness, exact feature column contract, and time-ordered splits
- Pipeline smoke test confirms run_feature_pipeline() correctly produces non-empty, time-ordered train/test splits from synthetic 100-row OHLCV data

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Write failing look-ahead bias + split order tests** - `1896b10` (test)
2. **Task 2 (GREEN): Implement ingest + features + labels to pass all tests** - `b9ac413` (feat)
3. **Task 3: Create ingest entrypoint script with S3 write and time-ordered split utility** - `bcca16f` (feat)

## Files Created/Modified

- `src/ingestion/coingecko.py` — fetch_ohlcv() (null guard), candles_to_dataframe(), write_raw_to_s3() via boto3.upload_fileobj
- `src/ingestion/ingest.py` — CLI entrypoint for Airflow PythonOperator; writes timestamped Parquet to S3
- `src/features/compute.py` — compute_features() producing FEATURE_COLS (12 columns); min_periods on every rolling call
- `src/features/labels.py` — label_volatility() using T+1..T+30 forward window, drops last 30 rows
- `src/features/pipeline.py` — run_feature_pipeline() → {full, train, test} with time-ordered 80/20 split assertion
- `tests/test_features.py` — 4 tests: look-ahead guard, split order, NaN warm-up, feature column contract
- `tests/test_ingest.py` — 1 test: ValueError on null candle field
- `src/__init__.py`, `src/ingestion/__init__.py`, `src/features/__init__.py` — empty package markers
- `tests/__init__.py` — empty package marker

## Decisions Made

- **RSI np.where(loss==0, 100):** Monotonic synthetic prices have zero loss throughout, making `replace(0, nan)` return NaN for all RSI values. Corrected to `np.where(loss==0, 100.0, ...)` which is the mathematically correct RSI value when there are no down-candles. This is not a test data limitation — it can occur in real data during strong bull runs.

- **compute_features does not drop NaN rows:** The function returns the full DataFrame including warm-up NaN rows, allowing callers to decide. pipeline.py drops them explicitly via `dropna(subset=FEATURE_COLS)`. This enables diagnostic inspection of warm-up behavior.

- **label_volatility slice is [i+1:i+31] (explicit comment):** A function docstring comments explicitly warn against changing this to [i:i+30], which would include row T in its own label window. The test_label_no_lookahead test enforces this invariant.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] RSI NaN on zero-loss (monotonic) price sequences**
- **Found during:** Task 2 (GREEN phase — running test_feature_no_nan_after_warmup)
- **Issue:** Plan's implementation used `loss.replace(0, np.nan)` to avoid division by zero. This correctly returns NaN for warm-up rows but also returns NaN when loss=0 after warm-up (e.g., monotonic ascending price sequence has no down-candles). The test uses monotonic synthetic prices, so rsi_14 was NaN for all 60 rows post-warmup.
- **Fix:** Replaced with `np.where(gain.isna() | loss.isna(), nan, np.where(loss==0, 100.0, 100 - (100 / (1 + gain / loss))))` — correctly handles warm-up NaN and the all-gain edge case
- **Files modified:** src/features/compute.py
- **Verification:** test_feature_no_nan_after_warmup passes; all 5 tests green
- **Committed in:** b9ac413 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in RSI formula)
**Impact on plan:** Auto-fix essential for correctness — the plan's `replace(0, nan)` approach silently produces NaN RSI during any strong trending period in real BTC data, corrupting Feast writes. No scope creep.

## Issues Encountered

None beyond the RSI deviation documented above.

## User Setup Required

None — no external service configuration required for this plan. AWS credentials and S3 bucket are required to run ingest.py in production (configured in Phase 1 Terraform output).

## Next Phase Readiness

- All three source modules export the correct symbols documented in plan frontmatter
- FEATURE_COLS is the single source of truth — Phase 2.2 Feast store.py must import it
- run_feature_pipeline() output dict is the contract for Phase 3 training DAG
- No feature computation exists in any serving path — confirmed constraint for Phase 4

---
*Phase: 02-data-and-feature-pipeline*
*Completed: 2026-03-12*
