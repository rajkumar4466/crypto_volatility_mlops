---
phase: 06-monitoring-and-drift-detection
plan: 01
subsystem: monitoring
tags: [scipy, ks-test, dynamodb, cloudwatch, airflow, boto3, drift-detection, mlops]

# Dependency graph
requires:
  - phase: 05-airflow-dag-orchestration
    provides: 7-task Airflow DAG with placeholder monitor task using run_script()
  - phase: 04-lambda-serving-and-api
    provides: DynamoDB prediction log with actual_label backfill schema (SERV-04, SERV-05)
  - phase: 03-model-training-and-registry
    provides: S3 current_metrics.json with model version; reference_features.parquet at model promotion
  - phase: 02-data-and-feature-pipeline
    provides: FEATURE_COLS list in src/features/compute.py; Feast offline store S3 Parquet layout
provides:
  - KS-test drift detection with 2-of-N gate across all 12 features (src/monitoring/drift.py)
  - Rolling accuracy computation from DynamoDB backfilled actuals (src/monitoring/accuracy.py)
  - CloudWatch metric publisher for 5 metrics in single API call (src/monitoring/alerts.py)
  - Airflow REST API retrain trigger via /api/v2 with JWT Bearer auth (src/monitoring/retrain_trigger.py)
  - Monitor task wired as Task 7 in DAG with full monitoring logic (dags/crypto_volatility_dag.py)
affects:
  - 06-02-monitoring-and-drift-detection (CloudWatch alarm Terraform; depends on metric names/namespace)
  - 07-dashboard-and-visualization (reads CryptoVolatility/Monitoring namespace metrics)

# Tech tracking
tech-stack:
  added: [scipy.stats.ks_2samp, s3fs (pandas parquet S3 support), requests]
  patterns:
    - 2-of-N gate for drift detection (min_drifted=2 prevents single-feature false positives)
    - Paginated DynamoDB scan with Attr() condition builder (avoids reserved word conflicts)
    - All-metrics-in-single-put_metric_data call pattern (CloudWatch free tier budget)
    - Timestamp-based dag_run_id for idempotent Airflow retrain trigger
    - Top-level try/except re-raise in monitor task (visibility without blocking DAG)

key-files:
  created:
    - src/monitoring/__init__.py
    - src/monitoring/drift.py
    - src/monitoring/accuracy.py
    - src/monitoring/alerts.py
    - src/monitoring/retrain_trigger.py
  modified:
    - dags/crypto_volatility_dag.py

key-decisions:
  - "Monitor task uses run_monitor() Python callable directly (not run_script) — enables direct import testing and avoids subprocess PATH issues for src.monitoring imports"
  - "FEATURE_NAMES constant exported from drift.py — single source of truth imported by DAG"
  - "Drift detection skipped gracefully when reference_df or recent_df unavailable (first run before model promotion)"
  - "retrain_count hardcoded to 0 for Phase 6 Plan 01 — enhanced post-Phase 6 per plan specification"
  - "LAMBDA_FUNCTION_NAME env var added for CloudWatch Duration metric lookup (defaults to crypto-volatility-predict)"

patterns-established:
  - "None value skipping: all monitoring metrics accept None; CloudWatch call skipped entirely if all None"
  - "409 Conflict idempotency: Airflow trigger returns gracefully on duplicate dag_run_id"
  - "Minimum sample gates: KS-test skips features with <30 samples; accuracy returns None below 10 items"

requirements-completed: [MON-01, MON-02, MON-03, MON-05, MON-06]

# Metrics
duration: 24min
completed: 2026-03-13
---

# Phase 6 Plan 01: Monitoring and Drift Detection Summary

**KS-test drift detection with 2-of-N gate, DynamoDB rolling accuracy, CloudWatch 5-metric publisher, and Airflow /api/v2 retrain trigger wired into the DAG monitor task**

## Performance

- **Duration:** 24 min
- **Started:** 2026-03-13T18:18:05Z
- **Completed:** 2026-03-13T18:42:48Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments
- Implemented `compute_drift()` using scipy KS-test with p<0.01 threshold and 2-of-N gate across all 12 BTC volatility features
- Implemented `compute_rolling_accuracy()` with paginated DynamoDB scan, returning None cleanly on empty/insufficient data
- Implemented `publish_metrics()` publishing exactly 5 CloudWatch metrics to `CryptoVolatility/Monitoring` in a single API call with model_version encoded as integer
- Implemented `trigger_retrain_dag()` posting to Airflow `/api/v2/dags/{dag_id}/dagRuns` with Bearer JWT auth and 409 idempotency
- Replaced placeholder `run_script("monitor.py")` in DAG with `run_monitor()` callable that wires all four monitoring modules

## Task Commits

Each task was committed atomically:

1. **Task 1: Drift detection and accuracy modules** - `6c5adea` (feat)
2. **Task 2: CloudWatch metric publisher and Airflow retrain trigger** - `24dc907` (feat)
3. **Task 3: Wire monitor task into Airflow DAG** - `9398b36` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/monitoring/__init__.py` - Empty package marker
- `src/monitoring/drift.py` - `compute_drift()` with scipy KS-test; 2-of-N gate; <30-sample skip logic
- `src/monitoring/accuracy.py` - `compute_rolling_accuracy()` with paginated DynamoDB scan; None on <10 items
- `src/monitoring/alerts.py` - `publish_metrics()` single put_metric_data to CryptoVolatility/Monitoring; 5 metrics
- `src/monitoring/retrain_trigger.py` - `trigger_retrain_dag()` via /api/v2; Bearer auth; 409 Conflict idempotency
- `dags/crypto_volatility_dag.py` - monitor task replaced with `run_monitor()` inline callable; all 7 tasks preserved

## Decisions Made
- Monitor task uses `run_monitor()` Python callable directly instead of `run_script("monitor.py")` — direct import avoids subprocess PATH issues for `src.monitoring` packages and enables cleaner testing
- `FEATURE_NAMES` list exported from `drift.py` as a module-level constant, imported by the DAG to maintain a single source of truth (alongside `FEATURE_COLS` in `src/features/compute.py`)
- Reference feature loading uses `pd.read_parquet("s3://...")` with s3fs; falls back gracefully when file not found (first run before model promotion writes the reference snapshot)
- `retrain_count` hardcoded to 0 per plan specification — enhanced post-Phase 6 when retrain history tracking is added

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed duplicate FilterExpression kwarg in DynamoDB scan call**
- **Found during:** Task 1 (accuracy.py implementation)
- **Issue:** Initial scan() call accidentally had both `FilterExpression=Attr(...)` and the boto3 condition builder form as separate kwargs — Python would raise a TypeError on duplicate keyword argument
- **Fix:** Removed the duplicate `Attr` import form; kept only the boto3 condition builder form which is the recommended pattern
- **Files modified:** `src/monitoring/accuracy.py`
- **Verification:** File parses cleanly; DynamoDB scan call has single FilterExpression
- **Committed in:** `6c5adea` (Task 1 commit, fixed before commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug)
**Impact on plan:** Required fix for correctness. No scope creep.

## Issues Encountered
- None beyond the duplicate kwarg bug (auto-fixed above)

## User Setup Required
None - no external service configuration required at this stage. CloudWatch alarms (SNS email) are Terraform resources delivered in Plan 06-02.

## Next Phase Readiness
- All four monitoring modules ready for integration testing against live AWS services
- `publish_metrics()` will populate `CryptoVolatility/Monitoring` namespace once DAG runs against real AWS credentials
- Plan 06-02 CloudWatch alarm Terraform depends on the metric names established here: `rolling_accuracy`, `drift_score`, `model_version`, `prediction_latency`, `retrain_count`
- Phase 7 (Dashboard) can read `CryptoVolatility/Monitoring` namespace metrics

## Self-Check: PASSED

All files verified present on disk. All task commits verified in git history.

---
*Phase: 06-monitoring-and-drift-detection*
*Completed: 2026-03-13*
