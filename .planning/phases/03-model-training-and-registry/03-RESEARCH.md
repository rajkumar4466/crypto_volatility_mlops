# Phase 3: Model Training and Registry - Research

**Researched:** 2026-03-12
**Domain:** XGBoost training pipeline, ONNX export/validation, W&B experiment tracking, S3 model registry with promotion gate
**Confidence:** MEDIUM (project SUMMARY.md verified stack; Context7 unavailable; Brave Search unavailable — findings drawn from project research archive + training knowledge)

## Summary

Phase 3 implements the Training Pipeline leg of the FTI architecture. It pulls point-in-time features from the Feast S3 offline store, trains an XGBoost classifier with GridSearchCV, exports the best estimator to ONNX, validates the export with a smoke test, logs everything to W&B, and writes artifacts to an S3 model registry. The promotion gate compares the challenger model's F1 against `current_metrics.json` before overwriting `current.onnx` — preventing a regression from silently replacing production.

The two biggest failure modes in this phase are (1) exporting the GridSearchCV wrapper instead of `best_estimator_`, which produces an ONNX model that cannot be loaded by onnxruntime, and (2) promoting without running the post-export smoke test, which passes a broken ONNX file to Phase 4 Lambda serving. Both failures are silent: the code runs without raising an exception, but the downstream Lambda either crashes at model-load time or returns garbage predictions. Every task in this phase must be verified standalone — the W&B run visible in the dashboard, the ONNX file loadable via `onnxruntime.InferenceSession`, the promotion gate correctly archiving or replacing — before wiring into the Phase 5 Airflow DAG.

Phase 3 is the most version-pinning-sensitive phase in the project. `onnxmltools`, `skl2onnx`, and `onnxruntime` must be pinned to exactly matching versions in both the training environment and the Phase 4 Lambda container. A version mismatch here manifests as a silent inference error or a shape mismatch that only surfaces at serving time.

**Primary recommendation:** Pin `xgboost==3.2.0`, `onnxmltools==1.16.0`, `skl2onnx==1.20.0`, `onnxruntime==1.24.3`, `wandb==0.25.1`. Export `grid_search.best_estimator_` only. Always run the post-export smoke test before S3 write and before promotion gate evaluation.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TRAIN-01 | XGBoost classifier with GridSearchCV (cross-validated hyperparameter tuning) | XGBoost 3.2.0 `XGBClassifier` with `sklearn.model_selection.GridSearchCV`; `n_jobs=1` to avoid OOM on t3.micro; `TimeSeriesSplit` for CV to prevent look-ahead bias |
| TRAIN-02 | Export trained model to ONNX via onnxmltools (export `best_estimator_`, not GridSearchCV wrapper) | `convert_sklearn(grid_search.best_estimator_, ...)` via onnxmltools 1.16.0; requires `update_registered_converters()` call before conversion; `initial_type` must match feature count exactly |
| TRAIN-03 | ONNX validation step: load exported model, run inference, assert output shape before writing to S3 | `onnxruntime.InferenceSession(model_path).run(None, {"X": sample_input})`; assert `output[0].shape == (1,)` and `output[1][0]` has keys `0` and `1` |
| TRAIN-04 | W&B experiment tracking: log params, metrics (accuracy, F1, ROC-AUC), feature importance, model artifact | `wandb.init()` → `wandb.log()` for metrics → `wandb.log({"feature_importance": wandb.plot.bar(...)})` → `wandb.save(onnx_path)` as artifact |
| TRAIN-05 | S3 JSON backup of run metrics (`runs/{run_id}/metrics.json`, `params.json`) | `boto3.put_object()` with `json.dumps(metrics)` to `s3://bucket/runs/{wandb.run.id}/metrics.json` and `params.json` |
| REG-01 | S3 versioned model storage: `models/current.onnx` (production) + `models/v{n}.onnx` (archived) | `boto3.copy_object()` to archive current → `boto3.upload_file()` for new current; version counter from `models/VERSION` file or S3 object listing |
| REG-02 | Promotion gate: new model replaces `current.onnx` only if F1 score exceeds current production model | Download `models/current_metrics.json` → compare `challenger_f1 > champion_f1` → promote or archive |
| REG-03 | Promotion decision logged to W&B and S3 (promoted/rejected, old vs new metrics) | `wandb.log({"promotion_decision": "promoted", "champion_f1": ..., "challenger_f1": ...})`; write `runs/{run_id}/promotion.json` to S3 |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| xgboost | 3.2.0 | Binary classifier (VOLATILE/CALM) | Trains in <2s on 288 samples; best tabular accuracy among tree methods; scikit-learn API for GridSearchCV compatibility |
| scikit-learn | 1.8.0 | GridSearchCV, TimeSeriesSplit, metrics | Standard ML utility; required by onnxmltools converter registration |
| onnxmltools | 1.16.0 | XGBoost → ONNX conversion | Required bridge; XGBoost 3.x has no native ONNX export |
| skl2onnx | 1.20.0 | ONNX converter framework (onnxmltools dependency) | Provides `update_registered_converters()`; must match onnxruntime version |
| onnxruntime | 1.24.3 | Post-export smoke test inference | Same runtime used in Phase 4 Lambda; version must match between training and serving |
| wandb | 0.25.1 | Experiment tracking dashboard | Free hosted; no server overhead; programmatic champion comparison |
| boto3 | 1.39.x | S3 artifact storage | AWS SDK; already in project stack |
| feast | 0.61.0 | Offline feature retrieval | Pulls point-in-time features from S3 Parquet store; prevents recomputing features in training |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pandas | 2.3.x | Feature DataFrame manipulation | Loading Feast offline store output, train/test split |
| numpy | 2.3.x | Array operations for ONNX input | Constructing smoke test input tensor |
| scipy | 1.17.x | (Phase 6 only — not needed here) | Skip in training requirements |
| joblib | (bundled with sklearn) | Model serialization fallback | Do not use for primary artifact — ONNX only |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| onnxmltools | XGBoost native `save_model('model.ubj')` | XGBoost binary format not loadable by onnxruntime; ONNX required for Lambda portability |
| W&B | MLflow server | MLflow requires hosting; W&B free tier has no server overhead; MLflow is explicitly out of scope |
| W&B | local JSON logs only | W&B provides visual dashboards and artifact versioning; both are used (W&B + S3 JSON backup) |
| GridSearchCV | Optuna | Optuna is v2 scope (ML-03); GridSearchCV is simpler, sufficient for this model size |
| TimeSeriesSplit | KFold | KFold shuffles data; time-series data requires forward-only splits to prevent look-ahead bias |

**Installation:**
```bash
pip install xgboost==3.2.0 scikit-learn==1.8.0 onnxmltools==1.16.0 skl2onnx==1.20.0 onnxruntime==1.24.3 wandb==0.25.1 feast==0.61.0 boto3
```

---

## Architecture Patterns

### Recommended Project Structure
```
training/
├── train.py              # Main training script (GridSearchCV → ONNX → W&B → S3)
├── registry.py           # Promotion gate logic (champion vs challenger comparison)
├── smoke_test.py         # Post-export ONNX validation
└── requirements.txt      # Pinned versions (must match Lambda container)

tests/
├── test_train.py         # Unit tests: feature loading, split, label distribution
├── test_registry.py      # Unit tests: promotion gate logic (mock S3)
└── test_smoke.py         # Unit test: ONNX output shape assertion
```

### Pattern 1: ONNX Export from GridSearchCV
**What:** Extract `best_estimator_` from GridSearchCV before converting to ONNX. The wrapper object itself is not convertible.
**When to use:** Every training run, immediately after `grid_search.fit()`.
**Example:**
```python
# Source: onnxmltools documentation + project SUMMARY.md (HIGH confidence)
from onnxmltools import convert_sklearn
from onnxmltools.utils import save_model
from skl2onnx.common.data_types import FloatTensorType
from onnxmltools.convert.xgboost.operator_converters.XGBoost import convert_xgboost
from skl2onnx import update_registered_converter
from skl2onnx.proto import onnx_proto

# REQUIRED: register XGBoost converter before calling convert_sklearn
update_registered_converter(
    XGBClassifier,
    "XGBoostXGBClassifier",
    convert_xgboost,
    parser=None,
)

n_features = X_train.shape[1]  # must be 12
initial_type = [("X", FloatTensorType([None, n_features]))]

# Export best_estimator_, NOT grid_search itself
onnx_model = convert_sklearn(
    grid_search.best_estimator_,
    initial_types=initial_type,
    target_opset=15,
)
save_model(onnx_model, "model.onnx")
```

### Pattern 2: Post-Export ONNX Smoke Test
**What:** Load the exported ONNX model with onnxruntime and run a single inference to verify output shape before writing to S3.
**When to use:** Immediately after export, before any S3 upload or promotion gate evaluation.
**Example:**
```python
# Source: onnxruntime documentation (MEDIUM confidence — training knowledge)
import onnxruntime as rt
import numpy as np

def smoke_test_onnx(model_path: str, n_features: int = 12) -> bool:
    """Returns True if model passes smoke test, raises on failure."""
    sess = rt.InferenceSession(model_path)
    sample = np.zeros((1, n_features), dtype=np.float32)
    input_name = sess.get_inputs()[0].name
    outputs = sess.run(None, {input_name: sample})
    # outputs[0]: predicted labels shape (1,)
    # outputs[1]: list of dicts with class probabilities
    assert outputs[0].shape == (1,), f"Unexpected label shape: {outputs[0].shape}"
    assert 0 in outputs[1][0] and 1 in outputs[1][0], "Missing class keys in prob output"
    return True
```

### Pattern 3: W&B Experiment Run
**What:** Initialize a W&B run at training start, log params and metrics, attach ONNX file as artifact.
**When to use:** Wrap the entire training → export → promote pipeline in a single `wandb.init()` context.
**Example:**
```python
# Source: W&B documentation (MEDIUM confidence — training knowledge)
import wandb

run = wandb.init(
    project="crypto-volatility-mlops",
    config=param_grid,  # logs all hyperparameter search space
    tags=["training", "xgboost"],
)

# After GridSearchCV fit:
wandb.log({
    "best_params": grid_search.best_params_,
    "accuracy": accuracy_score(y_test, y_pred),
    "f1": f1_score(y_test, y_pred),
    "roc_auc": roc_auc_score(y_test, y_prob),
})

# Feature importance (from best_estimator_)
importances = grid_search.best_estimator_.feature_importances_
feat_names = X_train.columns.tolist()
wandb.log({
    "feature_importance": wandb.plot.bar(
        wandb.Table(data=list(zip(feat_names, importances)), columns=["feature", "importance"]),
        "feature", "importance", title="Feature Importances"
    )
})

# Artifact upload
artifact = wandb.Artifact("xgboost-onnx", type="model")
artifact.add_file("model.onnx")
run.log_artifact(artifact)
wandb.finish()
```

### Pattern 4: Promotion Gate
**What:** Download `current_metrics.json` from S3, compare F1, promote or archive challenger.
**When to use:** After smoke test passes. Promotion gate is the final step before returning.
**Example:**
```python
# Source: project REQUIREMENTS.md + architecture (HIGH confidence for logic)
import boto3, json

s3 = boto3.client("s3")

def promote_or_archive(bucket, run_id, challenger_f1, onnx_path):
    # Load champion metrics (may not exist on first run)
    try:
        obj = s3.get_object(Bucket=bucket, Key="models/current_metrics.json")
        champion = json.loads(obj["Body"].read())
        champion_f1 = champion["f1"]
    except s3.exceptions.NoSuchKey:
        champion_f1 = 0.0  # first run always promotes

    if challenger_f1 > champion_f1:
        # Archive current model before overwriting
        try:
            s3.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": "models/current.onnx"},
                Key=f"models/v{run_id}.onnx",
            )
        except Exception:
            pass  # no current model on first run

        s3.upload_file(onnx_path, bucket, "models/current.onnx")
        s3.put_object(
            Bucket=bucket,
            Key="models/current_metrics.json",
            Body=json.dumps({"f1": challenger_f1, "run_id": run_id}),
        )
        decision = "promoted"
    else:
        s3.upload_file(onnx_path, bucket, f"models/v{run_id}.onnx")
        decision = "rejected"

    return decision, champion_f1
```

### Anti-Patterns to Avoid
- **Exporting GridSearchCV directly:** `convert_sklearn(grid_search, ...)` silently produces a broken ONNX model. Always use `grid_search.best_estimator_`.
- **Skipping the smoke test:** Writing an untested ONNX file to S3 passes a broken artifact to Phase 4 Lambda. Run `smoke_test_onnx()` before any S3 write.
- **Using KFold for cross-validation on time series:** KFold shuffles rows, creating look-ahead bias. Use `TimeSeriesSplit(n_splits=5)` in GridSearchCV.
- **Setting `n_jobs=-1` in GridSearchCV on t3.micro:** Parallel fitting exhausts 1GB RAM. Set `n_jobs=1` explicitly.
- **Version mismatch between training and serving:** If `skl2onnx` version in training differs from `onnxruntime` version in Lambda, inference shape may differ. Pin both in `requirements.txt` and Lambda `Dockerfile`.
- **Blindly overwriting `current.onnx`:** Omitting the promotion gate means every training run replaces production, including regressions.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| XGBoost → ONNX conversion | Custom protobuf serialization | onnxmltools 1.16.0 + skl2onnx 1.20.0 | Edge cases in tree structure encoding; operator versioning; opset compatibility |
| Hyperparameter search | Manual loop over param combinations | `GridSearchCV` with `TimeSeriesSplit` | Handles CV, best_params_, refit logic; compatible with onnxmltools export |
| Experiment dashboard | Custom HTML/JSON metric viewer | W&B free tier | Charts, artifact versioning, team sharing in 5 lines |
| ONNX model validation | Custom inference harness | `onnxruntime.InferenceSession` | Same runtime as Lambda; validates exact compatibility |
| Champion metric comparison | Manual F1 file tracking | `current_metrics.json` + boto3 | Simple, auditable, no extra service needed |

**Key insight:** The ONNX export pipeline has non-obvious converter registration requirements that change across versions. Do not attempt manual serialization.

---

## Common Pitfalls

### Pitfall 1: Exporting the GridSearchCV Wrapper
**What goes wrong:** `onnxmltools.convert_sklearn(grid_search)` raises a cryptic `ConverterError` or produces a zero-output ONNX model.
**Why it happens:** GridSearchCV is a meta-estimator; its internal structure is not what onnxmltools's XGBoost converter expects.
**How to avoid:** Always call `grid_search.fit()` first, then pass `grid_search.best_estimator_` to `convert_sklearn`.
**Warning signs:** Export completes without error but ONNX output shape is unexpected; `onnxruntime` raises `InvalidGraph` on load.

### Pitfall 2: Missing `update_registered_converter()` Call
**What goes wrong:** `convert_sklearn` raises `MissingConverter` or similar error for XGBClassifier.
**Why it happens:** onnxmltools does not auto-register XGBoost's converter; it must be explicitly registered before conversion.
**How to avoid:** Call `update_registered_converter(XGBClassifier, ...)` at module load time, before any conversion call.
**Warning signs:** `KeyError` or `MissingConverter` exception referencing `XGBoostXGBClassifier`.

### Pitfall 3: `initial_type` Feature Count Mismatch
**What goes wrong:** ONNX smoke test fails with `InvalidInput: Got invalid dimensions for input 'X'`.
**Why it happens:** `n_features` in `FloatTensorType([None, n_features])` does not match the actual feature count at inference time.
**How to avoid:** Derive `n_features` from `X_train.shape[1]` at runtime, never hardcode. The project specifies 12 features — assert this explicitly.
**Warning signs:** Smoke test raises shape error; Lambda inference fails with shape mismatch.

### Pitfall 4: Look-Ahead Bias in Training Split
**What goes wrong:** Model achieves >80% train accuracy on 288 samples — a red flag indicating data leakage.
**Why it happens:** Using random shuffle (default `train_test_split`) allows future data to appear in the training window.
**How to avoid:** Split by index cutoff: `X_train = X.iloc[:cutoff]`, `X_test = X.iloc[cutoff:]`. Use `TimeSeriesSplit` in GridSearchCV.
**Warning signs:** Training accuracy significantly above test accuracy; test accuracy on a 50/50 label distribution exceeds 75%.

### Pitfall 5: W&B Run Not Finishing Before Script Exit
**What goes wrong:** W&B run appears as "crashed" or metrics are incomplete in the dashboard.
**Why it happens:** Script exits before W&B background sync thread finishes uploading.
**How to avoid:** Always call `wandb.finish()` explicitly at the end of the script, or use the `wandb.init()` context manager.
**Warning signs:** W&B dashboard shows run in "running" state after script exits; metrics missing from final run summary.

### Pitfall 6: S3 Promotion Race Condition in Airflow
**What goes wrong:** Two concurrent training runs both see the same champion, both promote, overwriting each other.
**Why it happens:** No locking on `current.onnx` writes.
**How to avoid:** Phase 5 DAG enforces `max_active_runs=1`. At Phase 3 (standalone), this is not a concern. Document it as a constraint for Airflow integration.
**Warning signs:** `current_metrics.json` and `current.onnx` have different run IDs after a concurrent run.

---

## Code Examples

### Feast Offline Feature Retrieval for Training
```python
# Source: project research SUMMARY.md + Feast documentation (MEDIUM confidence)
from feast import FeatureStore
import pandas as pd

store = FeatureStore(repo_path="feature_repo/")

# Entity DataFrame: one row per training sample with event_timestamp
entity_df = pd.DataFrame({
    "entity_id": range(len(timestamps)),
    "event_timestamp": timestamps,
})

features = store.get_historical_features(
    entity_df=entity_df,
    features=[
        "btc_features:volatility_10m",
        "btc_features:volatility_30m",
        "btc_features:volatility_ratio",
        "btc_features:rsi_14",
        "btc_features:volume_spike",
        "btc_features:volume_trend",
        "btc_features:price_range_30m",
        "btc_features:sma_10_vs_sma_30",
        "btc_features:max_drawdown_30m",
        "btc_features:candle_body_avg",
        "btc_features:hour_of_day",
        "btc_features:day_of_week",
    ],
).to_df()
```

### GridSearchCV with TimeSeriesSplit
```python
# Source: scikit-learn documentation (HIGH confidence)
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from xgboost import XGBClassifier

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
    n_jobs=1,  # CRITICAL: avoid OOM on t3.micro
    random_state=42,
)

grid_search = GridSearchCV(
    clf,
    param_grid,
    cv=tscv,
    scoring="f1",
    n_jobs=1,  # outer loop also single-threaded
    verbose=1,
)
grid_search.fit(X_train, y_train)
```

### S3 Metrics Backup
```python
# Source: boto3 documentation pattern (HIGH confidence)
import boto3, json

s3 = boto3.client("s3")
run_id = wandb.run.id  # use W&B run ID as correlation key

metrics = {
    "accuracy": float(accuracy),
    "f1": float(f1),
    "roc_auc": float(roc_auc),
    "run_id": run_id,
    "timestamp": datetime.utcnow().isoformat(),
}
params = {
    "best_params": grid_search.best_params_,
    "run_id": run_id,
}

for key, data in [("metrics.json", metrics), ("params.json", params)]:
    s3.put_object(
        Bucket=BUCKET,
        Key=f"runs/{run_id}/{key}",
        Body=json.dumps(data),
        ContentType="application/json",
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| XGBoost native `save_model()` → custom loader | ONNX via onnxmltools → onnxruntime | XGBoost 1.x → 3.x | Lambda can load without XGBoost dependency; runtime is ~13MB vs ~130MB |
| MLflow self-hosted tracking | W&B free hosted | 2022 onward | No server to maintain; free tier sufficient for portfolio projects |
| KFold CV on all ML | TimeSeriesSplit for temporal data | Standard practice since ~2019 | Prevents look-ahead bias; required for all crypto/time-series training |
| Pickle model serialization | ONNX format | 2020 onward | Language-agnostic; Lambda-portable; version-stable across Python versions |

**Deprecated/outdated:**
- `use_label_encoder=True` in XGBClassifier: Deprecated in XGBoost 1.6, removed in 2.x. Set `use_label_encoder=False` explicitly.
- `XGBClassifier.get_booster().save_model('model.json')` for Lambda deployment: Requires XGBoost in Lambda; ONNX eliminates this dependency.

---

## Open Questions

1. **First-run promotion bootstrap**
   - What we know: `current_metrics.json` does not exist on first run; `get_object` raises `NoSuchKey`.
   - What's unclear: Whether to treat first run as auto-promote or require explicit flag.
   - Recommendation: Default `champion_f1 = 0.0` on `NoSuchKey` — first run always promotes. Document this behavior.

2. **Feast offline store availability at training time**
   - What we know: Phase 3 depends on Phase 2 completing successfully.
   - What's unclear: Whether the Feast S3 offline store path and feature view names are stable across environments.
   - Recommendation: Pass `FEAST_REPO_PATH` and `S3_BUCKET` as environment variables; document expected S3 prefix structure.

3. **W&B API key in CI/CD**
   - What we know: `wandb.init()` requires `WANDB_API_KEY` environment variable.
   - What's unclear: How to securely inject this in Phase 7 GitHub Actions and Phase 5 Airflow.
   - Recommendation: Store in AWS Secrets Manager; inject via environment variable in both Airflow task and GitHub Actions secret. Offline mode (`WANDB_MODE=offline`) for smoke tests that don't need the dashboard.

---

## Sources

### Primary (HIGH confidence)
- Project SUMMARY.md (2026-03-12) — verified stack versions, ONNX export pattern, pitfall catalog
- Project REQUIREMENTS.md — TRAIN-01 through TRAIN-05, REG-01 through REG-03 specifications
- Project ROADMAP.md — Phase 3 success criteria and plan sketches
- scikit-learn documentation — GridSearchCV, TimeSeriesSplit API (training knowledge, well-established)
- boto3 documentation — S3 put_object, upload_file patterns (training knowledge, stable API)

### Secondary (MEDIUM confidence)
- onnxmltools documentation — `convert_sklearn` + `update_registered_converter` pattern (training knowledge; Context7 unavailable for live verification)
- onnxruntime documentation — `InferenceSession.run()` API (training knowledge; well-established)
- W&B documentation — `wandb.init`, `wandb.log`, `wandb.Artifact` patterns (training knowledge; well-established)
- XGBoost Python API — `XGBClassifier`, `feature_importances_` attribute (training knowledge)

### Tertiary (LOW confidence)
- None for this phase — all critical patterns are covered by PRIMARY and SECONDARY sources from project SUMMARY.md

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified in project SUMMARY.md via PyPI (2026-03-12)
- Architecture: HIGH — derived directly from REQUIREMENTS.md and ROADMAP.md success criteria
- Pitfalls: MEDIUM — export and OOM pitfalls from project SUMMARY.md; W&B finish and race condition from training knowledge
- Code examples: MEDIUM — patterns are well-established but not live-verified against current library source (Context7 unavailable)

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (stable libraries; XGBoost/onnxmltools/skl2onnx version compatibility is the primary expiry risk)
