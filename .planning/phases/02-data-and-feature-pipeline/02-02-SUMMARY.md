---
phase: 02-data-and-feature-pipeline
plan: 02
subsystem: database
tags: [feast, feature-store, redis, s3, parquet, offline-store, online-store]

# Dependency graph
requires:
  - phase: 02-01
    provides: "12-feature compute.py + FEATURE_COLS list, feature pipeline, labels"
  - phase: 01-01
    provides: "S3 bucket, ElastiCache Redis cluster, Terraform outputs"
provides:
  - "feast/features.py: single-source-of-truth FeatureView with 12 fields + TTL 75min"
  - "feast/feature_store.yaml: S3 registry + S3 offline store + Redis online store config"
  - "src/features/store.py: write_to_feast_offline, run_materialize, spot_check_online_store, build_feast_entity_df"
  - "scripts/feast_setup.sh: one-time feast apply setup script for live AWS"
affects: [03-model-training, 04-serving-lambda, 06-drift-detection]

# Tech tracking
tech-stack:
  added: [feast==0.61.0]
  patterns:
    - "feast/features.py loaded via importlib.util.spec_from_file_location to avoid feast/ dir shadowing installed feast SDK"
    - "Feast feature repo directory NOT a Python package (no __init__.py) — feast apply uses CLI scan, not Python import"
    - "store.py never computes features — reads FEATURE_COLS from feast/features.py via importlib"

key-files:
  created:
    - feast/feature_store.yaml
    - feast/features.py
    - src/features/store.py
    - scripts/feast_setup.sh
  modified: []

key-decisions:
  - "feast/features.py is loaded via importlib.util.spec_from_file_location (not as Python package) to avoid Python namespace conflict between local feast/ directory and installed feast SDK"
  - "feast/ is NOT a Python package (no __init__.py) — this is the correct Feast ecosystem pattern; feast apply uses CLI directory scan"
  - "FeatureView TTL = 75 minutes (2.5x the 30-min materialization cycle) — stale features trigger re-materialize warning"
  - "build_feast_entity_df hardcodes symbol=BTCUSDT — correct for single-asset phase; generalize when multi-asset support added"
  - "run_materialize uses materialize_incremental when start_date=None — correct DAG pattern for recurring 30-min Airflow tasks"
  - "feast install: pip install feast==0.61.0 installed successfully; dill version conflict with multiprocess is cosmetic (no functional impact)"

patterns-established:
  - "importlib-load-feast-features: Always load feast/features.py via importlib.util.spec_from_file_location from store.py and any other consumer — never add feast/ to sys.path or create __init__.py there"
  - "feast-no-compute-in-serving: All feature computation in compute.py; store.py only reads/writes — enforces training/serving parity"

requirements-completed: [FEAT-01, FEAT-02, FEAT-03, FEAT-04]

# Metrics
duration: 6min
completed: 2026-03-12
---

# Phase 2 Plan 2: Feast Feature Store Integration Summary

**Feast 0.61.0 feature store wired to S3 offline store + Redis online store with 12-field FeatureView as single source of truth, offline write + incremental materialize functions, and importlib-based loading to avoid Python package namespace conflict**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-12T22:46:09Z
- **Completed:** 2026-03-12T22:52:00Z
- **Tasks:** 2 of 3 (Task 3 is a human-verify checkpoint — awaiting)
- **Files modified:** 4

## Accomplishments

- `feast/features.py`: authoritative single source of truth — btc_volatility_features FeatureView with all 12 feature Fields (Float32/Int32), TTL 75 minutes, S3 FileSource with env var substitution
- `feast/feature_store.yaml`: S3 registry + S3 offline store + Redis online store using `${FEAST_S3_BUCKET}`, `${REDIS_HOST}`, `${REDIS_PORT}` env vars (no hardcoded credentials)
- `src/features/store.py`: write_to_feast_offline, run_materialize (full + incremental), spot_check_online_store, build_feast_entity_df — all verified importable + smoke tested
- `scripts/feast_setup.sh`: executable one-time setup script (`feast apply` + `feature-views list`) for use when Phase 1 Terraform stack is live

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Feast feature store definitions** - `69e0ce9` (feat)
2. **Task 2: Implement Feast offline write + materialize functions** - `fc499e3` (feat)
3. **Task 3: Verify Feast integration end-to-end** - checkpoint (human-verify)

## Files Created/Modified

- `feast/features.py` - Single source of truth: 12-field FeatureView, FEATURE_COLS list, Entity btc_symbol
- `feast/feature_store.yaml` - Feast registry config (S3), offline store (S3 file), online store (Redis)
- `src/features/store.py` - Feast write/materialize/spot-check functions; importlib-based feature load
- `scripts/feast_setup.sh` - One-time feast apply setup for live AWS environment

## Decisions Made

**importlib-load pattern for feast/features.py:**
The local `feast/` directory (Feast feature repository) and the installed `feast` PyPI package share the same name. If `feast/` has an `__init__.py` and the project root is on sys.path, Python resolves `import feast` to the local directory, breaking `from feast import Entity` inside `features.py`. Solution: `feast/` has no `__init__.py` (correct Feast ecosystem pattern — it is a directory scanned by the CLI, not a Python package), and `store.py` loads `feast/features.py` using `importlib.util.spec_from_file_location`.

**TTL = 75 minutes:** 2.5x the 30-minute materialization interval. Any online feature older than 75 minutes is stale. `spot_check_online_store` warns if any feature is null, which indicates TTL expiry or missed materialization.

**feast install:** `pip install feast==0.61.0` installed successfully. A cosmetic dill version conflict (multiprocess requires dill>=0.4.0, feast installs 0.3.9) is logged but has no functional impact on this project's usage.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed Python namespace conflict: feast/ dir vs installed feast SDK**
- **Found during:** Task 1 (Feast feature store definitions)
- **Issue:** Plan specified creating `feast/__init__.py` as empty file. With `sys.path.insert(0, '.')`, the local `feast/` directory shadows the installed `feast` SDK. `from feast.features import btc_features` then fails because `features.py`'s `from feast import Entity` resolves to the empty local `__init__.py`.
- **Fix:** (a) Removed `feast/__init__.py` — feast/ is a CLI-scanned repo dir, not a Python package. (b) `features.py` imports from the installed feast SDK directly (works when loaded outside the local package context). (c) `store.py` loads `feast/features.py` via `importlib.util.spec_from_file_location` instead of `from feast.features import ...`. (d) Installed feast==0.61.0 via pip.
- **Files modified:** `feast/features.py`, `src/features/store.py` (design adapted from plan)
- **Verification:** `importlib.util.spec_from_file_location` load produces 12-field FeatureView; smoke test `build_feast_entity_df` passes
- **Committed in:** `69e0ce9`, `fc499e3`

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Essential correctness fix. The importlib pattern is strictly better — it's the canonical Feast ecosystem approach and eliminates the naming conflict permanently. All plan intent preserved.

## Issues Encountered

- **feast install on Python 3.13:** `pip install feast==0.61.0` succeeds. Minor dill version conflict (cosmetic, not functional).
- **Live AWS verification:** Deferred — requires Phase 1 Terraform stack running with ElastiCache Redis and S3 bucket. `scripts/feast_setup.sh` is ready to run when infrastructure is live.

## Feast 0.61.0 Behavior Discoveries

- `Entity` requires `value_type` in next release (DeprecationWarning) — plan's entity definition omits it; acceptable for now, add `value_type=ValueType.STRING` in Phase 3 if warning becomes error
- `FileSource` with S3 path requires `pyarrow` + boto3 for offline reads (already in Anaconda base)
- `feast apply` requires AWS credentials + live S3/Redis — confirmed not runnable locally without infra

## CoinGecko 1-min OHLCV Resolution

From Plan 02-01 execution: CoinGecko free tier provides 1-minute OHLCV for the past 1 day via `/coins/{id}/ohlc?vs_currency=usd&days=1`. This is sufficient for the feature pipeline's 30-row rolling warm-up + 30-row label forward window. Resolution is confirmed adequate.

## User Setup Required

**External services require manual configuration before `scripts/feast_setup.sh` can run:**

1. Phase 1 Terraform stack must be live (`terraform apply` complete)
2. Export env vars:
   ```bash
   export FEAST_S3_BUCKET=<from Terraform output>
   export REDIS_HOST=<ElastiCache cluster endpoint>
   export REDIS_PORT=6379
   export AWS_REGION=us-east-1
   ```
3. Run: `bash scripts/feast_setup.sh`
4. Run end-to-end pipeline to populate offline + online stores (see Task 3 checkpoint)

## Next Phase Readiness

- Feast feature contract established: `feast/features.py` is the anti-skew anchor for training and serving
- Phase 3 (model training) can read from Feast offline store once `feast apply` + `write_to_feast_offline` run
- Phase 4 (serving Lambda) reads from Redis online store via `store.get_online_features()` using same feature refs
- Blocker: Phase 1 infrastructure must be live before Feast offline/online stores can be populated

## Self-Check: PASSED

- FOUND: feast/feature_store.yaml
- FOUND: feast/features.py
- FOUND: src/features/store.py
- FOUND: scripts/feast_setup.sh (executable)
- FOUND: commit 69e0ce9 (Task 1)
- FOUND: commit fc499e3 (Task 2)

---
*Phase: 02-data-and-feature-pipeline*
*Completed: 2026-03-12*
