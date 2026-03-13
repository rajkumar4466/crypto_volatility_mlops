---
phase: 03-model-training-and-registry
verified: 2026-03-13T00:00:00Z
status: human_needed
score: 8/8 must-haves verified
human_verification:
  - test: "Live end-to-end training run with real Feast data"
    expected: "W&B run appears at https://wandb.ai/crypto-volatility-mlops with accuracy, f1, roc_auc metrics and a feature importance bar chart"
    why_human: "Requires Phase 2 Feast offline store to be populated with S3 Parquet data; W&B API key and live S3 bucket needed — cannot verify dashboard appearance programmatically"
  - test: "First-run promotion path"
    expected: "When no models/current_metrics.json exists, training completes and models/current.onnx is written to S3; current_metrics.json is created with the new champion's F1"
    why_human: "Requires live S3 bucket with no prior model; S3 state cannot be mocked without running the script"
  - test: "Challenger rejection path"
    expected: "When a second run produces lower F1 than champion: models/current.onnx is unchanged, models/v{run_id}.onnx archives the challenger, rejection.json records the decision"
    why_human: "Requires two sequential live runs against the same S3 bucket to observe the rejection gate in action"
  - test: "W&B ONNX artifact upload (gated by smoke test)"
    expected: "W&B run shows a model artifact named xgboost-onnx-{run_id}; if smoke test assertion fires, the artifact does NOT appear"
    why_human: "W&B artifact visibility requires dashboard inspection; failure path requires injecting a broken ONNX"
---

# Phase 3: Model Training and Registry Verification Report

**Phase Goal:** XGBoost trains on Feast offline features, exports to ONNX, logs to W&B, and only promotes to S3 registry if metrics improve over the current champion
**Verified:** 2026-03-13
**Status:** human_needed (all automated structural checks pass; live integration requires human verification)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `python training/train.py` completes without error and writes model.onnx to a local path | VERIFIED | `run_training()` writes to `/tmp/model.onnx` via `save_onnx_model()`; `if __name__ == "__main__":` block present with `sys.exit(0/1)` |
| 2 | Exported model.onnx passes smoke test: onnxruntime loads it, runs on (1,12) float32, returns output[0].shape == (1,) | VERIFIED | `smoke_test.py:30` uses `rt.InferenceSession(model_path)`; asserts `outputs[0].shape == (1,)`, both class keys, and list length; raises `AssertionError` on failure (never returns False) |
| 3 | GridSearchCV with TimeSeriesSplit selects best_params_ and best_estimator_ is the exported artifact | VERIFIED | `train.py:223` creates `TimeSeriesSplit(n_splits=5)`; `train.py:260` exports `grid_search.best_estimator_` explicitly, not `grid_search`; comment confirms intent |
| 4 | Training uses Feast offline store for features — no inline feature recomputation in train.py | VERIFIED | `_load_features_from_feast()` calls `store.get_historical_features()` at `train.py:129`; `FEATURE_NAMES` uses `btc_volatility_features:` prefix matching actual feast/features.py |
| 5 | Script exits non-zero if smoke test fails | VERIFIED | `smoke_test_onnx()` raises `AssertionError`; `run_training()` does not catch it; `__main__` block wraps in try/except and calls `sys.exit(1)` on any exception |
| 6 | W&B run logs params, metrics (accuracy, F1, ROC-AUC), feature importance bar chart, and ONNX artifact | VERIFIED (structural) | `train.py:194-202` `wandb.init()`; `train.py:278-283` logs metrics; `train.py:295-299` logs `wandb.plot.bar()`; `train.py:304-306` uploads artifact; `train.py:332-336` logs promotion_decision; `wandb.finish()` in finally block |
| 7 | When challenger F1 > champion F1: models/current.onnx is replaced; when challenger F1 <= champion F1: current.onnx is unchanged | VERIFIED (structural) | `registry.py:94` `if challenger_f1 > champion_f1:` branches to `_promote()` or `_archive()`; `_promote()` calls `s3.upload_file(onnx_path, bucket, "models/current.onnx")`; `_archive()` writes to `models/v{run_id}.onnx` only |
| 8 | First run (no current_metrics.json) always promotes | VERIFIED | `registry.py:83-88` catches `NoSuchKey`, sets `champion_f1 = 0.0`; any positive F1 challenger wins |

**Score:** 8/8 truths verified (structural/static analysis)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `training/train.py` | Main training script: Feast feature pull, GridSearchCV, ONNX export, smoke test | VERIFIED | 356 lines; substantive implementation with all required pipeline steps in documented order (steps 1-15) |
| `training/smoke_test.py` | ONNX post-export validation: `smoke_test_onnx(model_path, n_features=12) -> bool` | VERIFIED | 68 lines; correct signature; 3 assertions with descriptive messages; raises AssertionError (never silent) |
| `training/registry.py` | S3 model registry: `promote_or_archive()`, `backup_run_artifacts()` | VERIFIED | 276 lines; full champion/challenger logic with private helpers; `promotion.json` written both branches |
| `training/requirements.txt` | Pinned dependency versions matching Lambda container | VERIFIED | 10 lines; all 9 required packages present; critical triplet: `onnxmltools==1.16.0`, `skl2onnx==1.20.0`, `onnxruntime==1.24.3` |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `training/train.py` | `feature_repo/ (Feast)` | `FeatureStore.get_historical_features()` | WIRED | `train.py:84-132` — `_load_features_from_feast()` constructs `FeatureStore(repo_path=FEAST_REPO_PATH)`, reads batch source path, builds entity_df, calls `get_historical_features(entity_df, features=FEATURE_NAMES)` |
| `training/train.py` | `training/smoke_test.py` | `smoke_test_onnx(onnx_path)` | WIRED | `train.py:271-273` — imports and calls `smoke_test_onnx(onnx_path, n_features=12)` inside try block after ONNX export; exception propagates to `__main__` |
| `training/smoke_test.py` | `onnxruntime.InferenceSession` | `rt.InferenceSession(model_path).run()` | WIRED | `smoke_test.py:14,30,35` — `import onnxruntime as rt`; `sess = rt.InferenceSession(model_path)`; `outputs = sess.run(None, {input_name: sample})` |
| `training/train.py` | `wandb.run.id` | `wandb.init() -> run_id for S3 path` | WIRED | `train.py:194,304,312,319` — `run = wandb.init(...)` captures run object; `run.id` used in artifact name, passed to `backup_run_artifacts()` and `promote_or_archive()` |
| `training/train.py` | `training/registry.py` | `promote_or_archive(bucket, run_id, f1, onnx_path)` | WIRED | `train.py:67` module-level import; `train.py:317-323` calls `promote_or_archive()` with all required args; return values `(decision, champion_f1)` are used in the subsequent `wandb.log()` call |
| `training/registry.py` | `s3://bucket/models/current_metrics.json` | `boto3.get_object / put_object` | WIRED | `registry.py:75` `s3.get_object(Bucket=bucket, Key="models/current_metrics.json")`; `registry.py:214-224` `_put_json()` writes to same key on promotion |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| TRAIN-01 | 03-01-PLAN.md | XGBoost classifier with GridSearchCV | SATISFIED | `train.py:224-238` — `XGBClassifier` in `GridSearchCV(clf, param_grid, cv=tscv, scoring="f1", n_jobs=1)` |
| TRAIN-02 | 03-01-PLAN.md | Export trained model to ONNX via onnxmltools (export best_estimator_) | SATISFIED | `train.py:259-265` — `convert_sklearn(grid_search.best_estimator_, initial_types=initial_type, target_opset=15)` + `save_onnx_model()` |
| TRAIN-03 | 03-01-PLAN.md | ONNX validation: load, run inference, assert output shape before S3 write | SATISFIED | `smoke_test.py` entire implementation; called at `train.py:273` before any W&B or S3 upload (steps 7 precedes 10/11) |
| TRAIN-04 | 03-02-PLAN.md | W&B: params, metrics (accuracy, F1, ROC-AUC), feature importance, model artifact | SATISFIED (structural) | `wandb.init()`, `wandb.log({metrics, best_params})`, `wandb.plot.bar()`, `wandb.Artifact` upload all present in `train.py` |
| TRAIN-05 | 03-02-PLAN.md | S3 JSON backup: runs/{run_id}/metrics.json, params.json | SATISFIED (structural) | `registry.py:134-173` — `backup_run_artifacts()` writes both JSON files via `_put_json()`; called unconditionally before promotion |
| REG-01 | 03-02-PLAN.md | S3 versioned model storage: models/current.onnx + models/v{n}.onnx | SATISFIED (structural) | `_promote()` writes `models/current.onnx` and copies old to `models/v{champion_run_id}.onnx`; `_archive()` writes `models/v{run_id}.onnx` |
| REG-02 | 03-02-PLAN.md | Promotion gate: new model replaces current.onnx only if F1 exceeds current | SATISFIED (structural) | `registry.py:94` strict `>` comparison; NoSuchKey defaults champion_f1=0.0 for first run |
| REG-03 | 03-02-PLAN.md | Promotion decision logged to W&B and S3 (promoted/rejected, old vs new metrics) | SATISFIED (structural) | `_write_promotion_record()` writes `runs/{run_id}/promotion.json` both branches; `train.py:332-336` `wandb.log({promotion_decision, champion_f1_at_promotion, challenger_f1})` |

**All 8 requirement IDs from plan frontmatter accounted for. No orphaned requirements for Phase 3 in REQUIREMENTS.md.**

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | No anti-patterns detected |

No TODO/FIXME/placeholder comments found. No empty implementations. No silent failure patterns. `smoke_test_onnx` raises `AssertionError` rather than returning False. `S3_BUCKET` uses `os.environ["S3_BUCKET"]` (loud fail) rather than silent default. `wandb.finish()` is in a `finally` block ensuring it always runs.

---

## Notable Observations

**Missing `training/__init__.py`:** The `training/` directory has no `__init__.py`. Cross-module imports (`from training.smoke_test import smoke_test_onnx`, `from training.registry import ...`) rely on Python 3.3+ implicit namespace packages. This works when run as `python -m training.train` from the repo root. The `__pycache__` confirms `registry.py` and `smoke_test.py` were already imported successfully. This is not a blocker but should be noted for downstream phases (Phase 5 Airflow, Phase 7 CI) that import the training module.

**FEATURE_NAMES correction documented:** Plan 03-01 template used `btc_features:` prefix; implementation correctly uses `btc_volatility_features:` to match actual `feast/features.py`. This was an auto-fixed deviation documented in 03-01-SUMMARY.md.

---

## Human Verification Required

### 1. Live End-to-End Training Run

**Test:** With Phase 2 Feast offline store populated (`FEAST_REPO_PATH` set, `WANDB_API_KEY` set, `S3_BUCKET` set), run `python -m training.train`
**Expected:** W&B run appears at https://wandb.ai/crypto-volatility-mlops with `accuracy`, `f1`, `roc_auc` scalar metrics, a feature importance bar chart, and an ONNX model artifact; `aws s3 ls s3://{bucket}/runs/{run_id}/` shows `metrics.json`, `params.json`, `promotion.json`
**Why human:** Requires live Feast S3 offline store (Phase 2 prerequisite), live W&B API key, and live S3 bucket; W&B dashboard appearance cannot be verified programmatically

### 2. First-Run Promotion Path

**Test:** With an empty S3 bucket (no `models/current_metrics.json`), run training once
**Expected:** `models/current.onnx` and `models/current_metrics.json` are created; promotion output shows `decision=promoted`, `champion_f1=0.0`; `runs/{run_id}/promotion.json` records the decision
**Why human:** Requires live S3 bucket in a clean state; S3 side effects cannot be mocked without running the full script

### 3. Challenger Rejection Path

**Test:** Run training twice against the same S3 bucket; second run should produce lower F1 (or inject one artificially)
**Expected:** Second run: `models/current.onnx` is unchanged; `models/v{run_id}.onnx` archives the challenger; `runs/{run_id}/promotion.json` shows `decision=rejected`; W&B run shows `promotion_decision=rejected`
**Why human:** Requires two sequential live runs; F1 comparison behavior cannot be verified without live S3 state

### 4. Smoke Test Gate (Broken ONNX)

**Test:** Inject a corrupt ONNX file at `/tmp/model.onnx` (e.g., write random bytes) and trigger smoke test
**Expected:** `smoke_test_onnx()` raises `AssertionError` with a descriptive message; no W&B artifact upload; no S3 upload; script exits non-zero
**Why human:** Requires deliberately corrupting an ONNX artifact mid-run to observe failure propagation

---

## Gaps Summary

No structural gaps found. All 4 required artifacts exist and are substantive (not stubs). All 6 key links are wired with real logic (not placeholders). All 8 requirement IDs are satisfied by identifiable code. The phase goal is structurally complete.

The `human_needed` status reflects that the most critical behaviors — W&B dashboard visibility, live S3 promotion gate, and first-run bootstrap — require actual infrastructure to verify. These are integration behaviors, not implementation gaps.

---

_Verified: 2026-03-13_
_Verifier: Claude (gsd-verifier)_
