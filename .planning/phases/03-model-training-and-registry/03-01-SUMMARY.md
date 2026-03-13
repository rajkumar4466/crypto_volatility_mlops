---
phase: 03-model-training-and-registry
plan: 01
subsystem: training
tags: [xgboost, onnx, onnxmltools, skl2onnx, onnxruntime, feast, gridsearchcv, timeseriessplit]

# Dependency graph
requires:
  - phase: 02-data-and-feature-pipeline
    provides: Feast offline store (S3 Parquet) with 12 btc_volatility_features columns + label
provides:
  - training/train.py — run_training() returning (onnx_path, metrics_dict, best_params_dict)
  - training/smoke_test.py — smoke_test_onnx(model_path, n_features=12) raising on failure
  - training/requirements.txt — pinned onnxmltools/skl2onnx/onnxruntime triplet for Lambda parity
affects:
  - 03-02-model-registry (consumes run_training() return value, WANDB_API_KEY, S3_BUCKET env)
  - 04-lambda-serving (must match onnxruntime==1.24.3 in Lambda container)
  - 05-airflow-orchestration (calls run_training() inside training DAG task)

# Tech tracking
tech-stack:
  added:
    - xgboost==3.2.0 (XGBClassifier binary classifier)
    - onnxmltools==1.16.0 (XGBoost -> ONNX conversion bridge)
    - skl2onnx==1.20.0 (ONNX converter framework, update_registered_converter)
    - onnxruntime==1.24.3 (post-export smoke test, matches Lambda runtime)
    - scikit-learn==1.8.0 (GridSearchCV, TimeSeriesSplit, accuracy/f1/roc_auc metrics)
    - wandb==0.25.1 (placeholder pinned; W&B calls added in Plan 03-02)
  patterns:
    - Module-level update_registered_converter() before any convert_sklearn() call
    - Export grid_search.best_estimator_ NOT GridSearchCV wrapper to ONNX
    - Time-ordered index split (not shuffle) for train/test to prevent look-ahead bias
    - TimeSeriesSplit(n_splits=5) inside GridSearchCV for CV
    - n_jobs=1 on both XGBClassifier and GridSearchCV (OOM guard on t3.micro)
    - Smoke test raises AssertionError — never returns False silently

key-files:
  created:
    - training/train.py
    - training/smoke_test.py
    - training/requirements.txt
  modified: []

key-decisions:
  - "update_registered_converter(XGBClassifier, ...) at module level — prevents MissingConverter at conversion time"
  - "Export grid_search.best_estimator_ (not wrapper) — GridSearchCV cannot be converted to ONNX directly"
  - "Feature view name is btc_volatility_features and join key is symbol — matches feast/features.py exactly"
  - "FEATURE_NAMES uses btc_volatility_features: prefix (not btc_features: as in plan template) — corrected to match actual Feast setup"
  - "smoke_test_onnx raises AssertionError on failure so train.py exits non-zero — broken ONNX never propagates"
  - "n_jobs=1 on both GridSearchCV and XGBClassifier — required on t3.micro to avoid OOM"
  - "80/20 time-ordered split by iloc index cutoff — no shuffle"

patterns-established:
  - "Pattern 1: ONNX export — always register converter at module load, export best_estimator_, run smoke test before returning"
  - "Pattern 2: Feast read in training — use get_historical_features() with entity_df; read source path from feature_view.batch_source.path to discover available timestamps"
  - "Pattern 3: Time-series CV — TimeSeriesSplit not KFold; index-cutoff split not train_test_split"

requirements-completed: [TRAIN-01, TRAIN-02, TRAIN-03]

# Metrics
duration: ~56min
completed: 2026-03-13
---

# Phase 3 Plan 01: Model Training Pipeline Summary

**XGBoost GridSearchCV + ONNX export pipeline with post-export smoke test gate — no broken model can propagate downstream**

## Performance

- **Duration:** ~56 min
- **Started:** 2026-03-13T00:04:38Z
- **Completed:** 2026-03-13T01:00:17Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- Built complete training pipeline: Feast offline pull -> GridSearchCV with TimeSeriesSplit -> ONNX export -> smoke test gate
- Registered XGBoost ONNX converter at module level, exports best_estimator_ (not wrapper) to prevent silent broken models
- Pinned the critical onnxmltools==1.16.0 / skl2onnx==1.20.0 / onnxruntime==1.24.3 triplet that must match Phase 4 Lambda container

## Task Commits

Each task was committed atomically:

1. **Task 1: Create training/requirements.txt with pinned versions** - `2bd4c3b` (chore)
2. **Task 2: Create training/smoke_test.py — ONNX post-export validator** - `1d34cbe` (feat)
3. **Task 3: Create training/train.py — GridSearchCV + ONNX export pipeline** - `b33ca04` (feat)

## Files Created/Modified
- `training/requirements.txt` - Pinned 9 packages; onnxmltools/skl2onnx/onnxruntime triplet must match Lambda container
- `training/smoke_test.py` - smoke_test_onnx(model_path, n_features=12) -> bool; loads ONNX, asserts output shape and both class keys; raises AssertionError on failure
- `training/train.py` - run_training() -> (onnx_path, metrics_dict, best_params_dict); full pipeline with Feast pull, GridSearchCV, ONNX export, smoke test gate

## Decisions Made

- **update_registered_converter at module level:** Called before any function, not inside run_training(). Missing this causes a MissingConverter exception at conversion time that is non-obvious to debug.
- **Export best_estimator_ not wrapper:** GridSearchCV itself is not ONNX-convertible. Exporting the wrapper produces a silent broken model — a known pitfall from research.
- **Feature view name correction:** Plan template showed `btc_features:` prefix but the actual Feast setup in feast/features.py uses `btc_volatility_features:` as the view name and `symbol` as the join key. Corrected in implementation.
- **smoke_test_onnx raises, never returns False:** train.py gets an exception if the ONNX is broken — the script exits non-zero, preventing a bad artifact from propagating to S3 or Lambda.
- **n_jobs=1 on both clf and grid_search:** Enforced as documented OOM guard for t3.micro (1GB RAM). Do not change without profiling.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected Feast feature view name from btc_features to btc_volatility_features**
- **Found during:** Task 3 (train.py implementation)
- **Issue:** Plan template used `btc_features:` prefix in FEATURE_NAMES, but actual feast/features.py defines the view as `btc_volatility_features` and entity join key as `symbol` (not `entity_id`)
- **Fix:** Used `btc_volatility_features:` as feature view prefix and `symbol` as entity join key in entity_df construction; read source path from `feature_view.batch_source.path` for timestamp discovery
- **Files modified:** training/train.py
- **Verification:** Structural AST check passes; all feature name references consistent with feast/features.py
- **Committed in:** b33ca04 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: feature view name mismatch between plan template and actual Feast setup)
**Impact on plan:** Fix essential for correctness — using wrong view name would cause get_historical_features() to fail at runtime. No scope creep.

## Issues Encountered
None — plan structure was clear; single deviation was a plan template vs. actual code mismatch, auto-corrected inline.

## User Setup Required
None - no external service configuration required in this plan. W&B API key and S3 bucket are used in Plan 03-02.

## Next Phase Readiness
- Plan 03-02 can call `run_training()` and receive `(onnx_path, metrics, best_params)` tuple
- Plan 03-02 needs: WANDB_API_KEY env var, S3_BUCKET env var, boto3 S3 upload, W&B logging calls
- Phase 4 Lambda must pin onnxruntime==1.24.3 to match training environment (already in decisions)
- Live execution requires: Phase 2 feature pipeline must have populated Feast offline store (S3 Parquet) before `python -m training.train` can run end-to-end

## Self-Check: PASSED

All created files found on disk. All task commits verified in git history.

---
*Phase: 03-model-training-and-registry*
*Completed: 2026-03-13*
