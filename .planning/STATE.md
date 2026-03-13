---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-13T18:15:27.687Z"
progress:
  total_phases: 7
  completed_phases: 5
  total_plans: 11
  completed_plans: 8
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-12)

**Core value:** A working, observable MLOps loop where data drift triggers automated retraining, model evaluation, and promotion — all visible through dashboards and alerts within hours.
**Current focus:** Phase 5 — Airflow DAG Orchestration (Plan 01 complete, checkpoint awaiting human verification)

## Current Position

Phase: 5 of 7 (Airflow DAG Orchestration) — Plan 01 automated tasks complete
Plan: 1 of 1 in phase — Plan 05-01 automated tasks COMPLETE (Task 3: human-verify checkpoint pending)
Status: Phase 5 automated work done — awaiting human verification of deployed Airflow instance
Last activity: 2026-03-13 — Plan 05-01: airflow_setup.sh, crypto_volatility_dag.py (7-task DAG with trigger_rule skip enforcement), systemd service files

Progress: [████████░░] 73%

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: ~15 min
- Total execution time: ~103 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure-foundation | 2 | ~6 min | ~3 min |
| 02-data-and-feature-pipeline | 2 | ~12 min | ~6 min |
| 03-model-training-and-registry | 2 of 2 | ~71 min | ~35 min |
| 04-lambda-serving-and-api | 1 of 1 | ~14 min | ~14 min |
| 05-airflow-dag-orchestration | 1 of 1 | ~8 min | ~8 min |

**Recent Trend:**
- Last 5 plans: 05-01 (~8 min), 04-01 (~14 min), 03-02 (~15 min), 03-01 (~56 min), 02-02 (~6 min)
- Trend: Stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- All phases: Python 3.11 is the required runtime (hard lower bound from pandas/scipy/scikit-learn/Airflow version constraints)
- Phase 1: Configure EC2 swap (4GB) in Terraform user-data, not manually post-launch
- Phase 1: Set billing alarm at $1 before any `terraform apply` — non-negotiable
- Phase 4: Use x86_64 Lambda architecture (ARM64 has ONNX Runtime illegal instruction bug)
- Phase 6: KS-test p-value threshold 0.01 (not 0.05) to reduce false positives on volatile crypto data; alert only if 2+ features drift
- Phase 1 (01-02): SequentialExecutor for Airflow (not CeleryExecutor) — matches t3.micro RAM constraint; no workers or broker config needed
- Phase 1 (01-02): Profile-gated airflow-init (profiles=[init]) prevents accidental DB re-migration on every docker compose up
- Phase 1 (01-02): postgres:16 and redis:7-alpine chosen to match Terraform RDS engine_version=16 and ElastiCache engine_version=7.1
- Phase 1 (01-01): DynamoDB PROVISIONED billing mode (5 RCU/5 WCU) — PAY_PER_REQUEST disqualifies always-free 25 WCU/RCU tier
- Phase 1 (01-01): ElastiCache aws_elasticache_cluster (cache.t3.micro) NOT Serverless — Serverless has no free tier
- Phase 1 (01-01): API Gateway HTTP API v2 (aws_apigatewayv2_api) not REST API v1 — 70% cheaper, simpler for GET endpoints
- Phase 1 (01-01): Lambda architectures=x86_64 confirmed — ARM64 ONNX Runtime illegal instruction bug
- Phase 1 (01-01): Billing alarm via provider alias aws.billing (us-east-1) — billing metrics only exist there
- Phase 1 (01-01): SG chaining (reference SG IDs not CIDR) for Lambda→Redis access
- Phase 2 (02-01): RSI uses np.where(loss==0, 100) not replace(0, nan) — monotonic price sequences produce zero loss; NaN RSI would corrupt Feast writes
- Phase 2 (02-01): label_volatility slice is [i+1:i+31] not [i:i+30] — FEATURE_COLS in compute.py is single source of truth for downstream Feast/Lambda/drift imports
- Phase 2 (02-01): SWING_THRESHOLD = 0.02 (2%) for VOLATILE/CALM label boundary on BTC 1-min data
- [Phase 02-data-and-feature-pipeline]: feast/features.py loaded via importlib.util.spec_from_file_location to avoid feast/ dir shadowing installed feast SDK (no __init__.py in feast/ dir)
- [Phase 02-data-and-feature-pipeline]: FeatureView TTL = 75min (2.5x 30-min cycle); feast/ dir is not a Python package -- CLI-scanned Feast repo dir only
- [Phase 03-model-training-and-registry]: update_registered_converter(XGBClassifier) at module level in train.py — prevents MissingConverter at ONNX conversion time
- [Phase 03-model-training-and-registry]: Export grid_search.best_estimator_ (not GridSearchCV wrapper) to ONNX — wrapper is not convertible by onnxmltools
- [Phase 03-model-training-and-registry]: Feature view name is btc_volatility_features (not btc_features) — join key is symbol matching feast/features.py entity definition
- [Phase 03-02 registry]: wandb.run.id used as correlation key for all S3 artifact paths (runs/{run_id}/*) — single ID links W&B run to S3 metrics, params, promotion record, and ONNX archive
- [Phase 03-02 registry]: champion_f1=0.0 default when current_metrics.json absent — NoSuchKey is expected on first run; any challenger with F1 > 0 promotes
- [Phase 03-02 registry]: try/finally for wandb.finish() in run_training() — guarantees W&B run closes cleanly even if S3 upload or promotion raises
- [Phase 03-02 registry]: S3_BUCKET read via os.environ["S3_BUCKET"] with no default — KeyError is intentional loud failure if env var missing
- [Phase 04-lambda-serving-and-api]: feature_store.yaml rendered at Lambda INIT to /tmp — REDIS_HOST and S3_BUCKET injected as env vars
- [Phase 04-lambda-serving-and-api]: Separate Dockerfile.backfill for lighter backfill Lambda image (requests only, no onnxruntime/feast)
- [Phase 04-lambda-serving-and-api]: CoinGecko free tier is day-granular — backfill uses daily price proxy; Phase 5 refines with OHLCV
- [Phase 05-airflow-dag-orchestration]: Airflow 2.10.4 with pip constraint file prevents dependency conflicts on shared EC2 instance
- [Phase 05-airflow-dag-orchestration]: TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS on retrain and promote — skipped upstream yields orange skip, not red failure
- [Phase 05-airflow-dag-orchestration]: TriggerRule.ALL_DONE on monitor — always emits observability signals even when pipeline partially fails
- [Phase 05-airflow-dag-orchestration]: max_active_runs=1 prevents concurrent DAG runs racing over Feast materialization and model registry state

### Pending Todos

None yet.

### Blockers/Concerns

- ElastiCache free tier: only available for AWS accounts created before July 15, 2025 — verify account creation date before Phase 1
- Phase 2 (Feast): `feast apply` schema migration behavior and `feast materialize_incremental` timing have MEDIUM confidence — validate against Feast 0.61.0 changelog during planning
- Phase 4 (Lambda VPC): Lambda VPC subnet/security group config for ElastiCache access is a known complexity point — research flags this for deeper investigation during Phase 4 planning
- Phase 6 (drift thresholds): KS-test 0.01 p-value and "2+ features" rule are community estimates — backtest against historical BTC data before wiring to retrain trigger

## Session Continuity

Last session: 2026-03-13
Stopped at: Completed 05-01-PLAN.md automated tasks — airflow_setup.sh, crypto_volatility_dag.py, systemd service files. Task 3 checkpoint (human-verify) awaiting deployment on EC2+RDS.
Resume file: None
