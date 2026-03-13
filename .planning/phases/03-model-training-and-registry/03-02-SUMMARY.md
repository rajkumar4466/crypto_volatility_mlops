---
phase: 03-model-training-and-registry
plan: 02
subsystem: training
tags: [wandb, boto3, s3, model-registry, champion-challenger, onnx, xgboost, experiment-tracking]

# Dependency graph
requires:
  - phase: 03-model-training-and-registry
    plan: 01
    provides: run_training() returning (onnx_path, metrics, best_params); smoke_test_onnx gate
  - phase: 02-data-and-feature-pipeline
    provides: Feast offline store (S3 Parquet) with 12 btc_volatility_features columns + label
provides:
  - training/registry.py — promote_or_archive() and backup_run_artifacts(); S3 model registry
  - training/train.py — augmented with W&B tracking, S3 backup, and registry promotion gate
affects:
  - 04-lambda-serving (downloads current.onnx from S3; needs current_metrics.json to exist)
  - 05-airflow-orchestration (calls run_training() inside training DAG; S3 artifacts written)
  - 06-drift-detection (reads current_metrics.json to compare against retraining results)

# Tech tracking
tech-stack:
  added:
    - wandb==0.25.1 (experiment tracking; WANDB_MODE=offline for CI)
    - boto3 (S3 upload/download; from aws-sdk already present in Phase 1 infra)
  patterns:
    - wandb.run.id used as correlation key for all S3 artifact paths (runs/{run_id}/*)
    - champion_f1 defaults to 0.0 when current_metrics.json absent (first-run always promotes)
    - try/finally for wandb.finish() — guaranteed call even on exception
    - ONNX artifact uploaded to W&B only after smoke_test_onnx passes (no broken model uploaded)
    - S3 layout: models/current.onnx (champion), models/current_metrics.json, models/v{run_id}.onnx (archived), runs/{run_id}/*.json

key-files:
  created:
    - training/registry.py
  modified:
    - training/train.py

key-decisions:
  - "wandb.run.id used as run correlation key — single identifier links W&B run, S3 metrics/params/promotion records, and ONNX artifact paths"
  - "champion_f1=0.0 default for first run — NoSuchKey on models/current_metrics.json is expected, not an error; challenger always wins first run"
  - "try/finally for wandb.finish() in run_training() — finish() must be called even if S3 backup, promotion, or any upstream step raises"
  - "ONNX artifact uploaded to W&B only after smoke_test_onnx passes — broken ONNX never reaches W&B or S3"
  - "backup_run_artifacts called unconditionally before promote_or_archive — every run is auditable regardless of promotion outcome"
  - "S3_BUCKET read via os.environ[S3_BUCKET] with no default — KeyError is intentional loud failure if env var missing"

patterns-established:
  - "Pattern 4: W&B correlation — wandb.init() first, use run.id as key, wandb.finish() in finally"
  - "Pattern 5: Champion/challenger gate — load current_metrics.json (default 0.0 on NoSuchKey), compare F1, promote or archive, write promotion.json always"

requirements-completed: [TRAIN-04, TRAIN-05, REG-01, REG-02, REG-03]

# Metrics
duration: ~15min
completed: 2026-03-13
---

# Phase 3 Plan 02: W&B Tracking + S3 Model Registry Summary

**W&B experiment tracking with feature importance charts, S3 metrics backup per run, and F1-gated champion/challenger promotion writing current.onnx only when challenger beats champion**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-13T14:55:20Z
- **Completed:** 2026-03-13T15:10:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created training/registry.py with promote_or_archive() implementing champion/challenger F1 gate and backup_run_artifacts() for per-run S3 audit trail
- Augmented training/train.py with full W&B integration: wandb.init(), metrics + feature importance bar chart + ONNX artifact upload, and promotion decision logging
- Wired wandb.run.id as the single correlation key linking W&B runs, S3 artifact paths (runs/{run_id}/*), and ONNX archives (models/v{run_id}.onnx)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create training/registry.py — S3 model registry with promotion gate** - `0370784` (feat)
2. **Task 2: Augment training/train.py — W&B tracking + S3 backup + registry integration** - `1943832` (feat)

## Files Created/Modified
- `training/registry.py` - promote_or_archive(bucket, run_id, challenger_f1, onnx_path, challenger_metrics) -> (decision, champion_f1); backup_run_artifacts(bucket, run_id, metrics, params); handles first-run NoSuchKey gracefully
- `training/train.py` - Augmented run_training() with wandb.init/log/finish, feature importance bar chart, ONNX artifact upload, S3 backup, and registry promotion gate; try/finally ensures wandb.finish() always called

## Decisions Made

- **wandb.run.id as correlation key:** All S3 artifact paths use run.id (runs/{run_id}/metrics.json, runs/{run_id}/params.json, runs/{run_id}/promotion.json, models/v{run_id}.onnx). This makes it trivial to reconstruct the full history of any run from W&B or S3 alone.

- **champion_f1=0.0 for first run:** When models/current_metrics.json does not exist, NoSuchKey is expected and caught. Setting champion_f1=0.0 means any challenger with F1 > 0 will promote — correct for the first run.

- **try/finally for wandb.finish():** Placed around all post-init logic so the W&B run always closes cleanly. Without this, a failed S3 upload or promotion error would leave a dangling W&B run.

- **ONNX artifact upload gated by smoke test:** The smoke_test_onnx() call is step 7; W&B artifact upload is step 10. A broken ONNX raises AssertionError at step 7, preventing any artifact from reaching W&B or S3.

- **backup_run_artifacts before promote_or_archive:** Metrics and params are written to S3 unconditionally before the promotion decision, ensuring every run is auditable even if the promotion call fails.

- **S3_BUCKET with no default:** os.environ["S3_BUCKET"] (not .get()) raises KeyError if missing. Silent empty-string default would cause confusing S3 errors; loud failure at startup is preferable.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None — implementation matched plan specification precisely.

## User Setup Required

**External services require manual configuration.** The following env vars must be set before running training/train.py live:

| Variable | Source |
|---|---|
| `WANDB_API_KEY` | W&B Dashboard -> Settings -> API Keys (https://wandb.ai/settings) |
| `S3_BUCKET` | Terraform output from Phase 1: `terraform output s3_bucket_name` |
| `AWS_DEFAULT_REGION` | Set to your deployed region (e.g. us-east-1) |
| `FEAST_REPO_PATH` | Path to Feast repo directory (default: feast/) |

For CI/offline testing: set `WANDB_MODE=offline` to bypass W&B API auth.

Verify after live run:
```bash
# W&B run visible at:
# https://wandb.ai/crypto-volatility-mlops

# S3 artifacts written:
aws s3 ls s3://<bucket>/runs/<run_id>/
# Expected: metrics.json, params.json, promotion.json

aws s3 ls s3://<bucket>/models/
# Expected: current.onnx, current_metrics.json, v<run_id>.onnx
```

## Next Phase Readiness
- Phase 4 (Lambda serving): `models/current.onnx` in S3 is the artifact to download; `models/current_metrics.json` contains the champion F1 for observability dashboards
- Phase 5 (Airflow): `run_training()` signature unchanged — DAG task calls it and receives `(onnx_path, metrics, best_params)` as before; no Airflow-side changes needed
- Phase 6 (Drift detection): `models/current_metrics.json` provides the baseline F1 against which post-retraining improvements are measured

## Self-Check: PASSED

---
*Phase: 03-model-training-and-registry*
*Completed: 2026-03-13*
