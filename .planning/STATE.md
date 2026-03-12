---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-12T22:42:10Z"
progress:
  total_phases: 7
  completed_phases: 1
  total_plans: 11
  completed_plans: 3
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-12)

**Core value:** A working, observable MLOps loop where data drift triggers automated retraining, model evaluation, and promotion — all visible through dashboards and alerts within hours.
**Current focus:** Phase 2 — Data and Feature Pipeline

## Current Position

Phase: 2 of 7 (Data and Feature Pipeline)
Plan: 1 of 2 in current phase
Status: In progress — Plan 02-01 complete, Plan 02-02 next
Last activity: 2026-03-12 — Plan 02-01 complete: CoinGecko ingest + 12 features + VOLATILE/CALM labels with TDD look-ahead bias guards

Progress: [███░░░░░░░] 21%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: ~4 min
- Total execution time: ~12 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure-foundation | 2 | ~6 min | ~3 min |
| 02-data-and-feature-pipeline | 1 | ~6 min | ~6 min |

**Recent Trend:**
- Last 5 plans: 02-01 (~6 min), 01-02 (~1 min), 01-01 (~5 min)
- Trend: N/A (small sample)

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

### Pending Todos

None yet.

### Blockers/Concerns

- ElastiCache free tier: only available for AWS accounts created before July 15, 2025 — verify account creation date before Phase 1
- Phase 2 (Feast): `feast apply` schema migration behavior and `feast materialize_incremental` timing have MEDIUM confidence — validate against Feast 0.61.0 changelog during planning
- Phase 4 (Lambda VPC): Lambda VPC subnet/security group config for ElastiCache access is a known complexity point — research flags this for deeper investigation during Phase 4 planning
- Phase 6 (drift thresholds): KS-test 0.01 p-value and "2+ features" rule are community estimates — backtest against historical BTC data before wiring to retrain trigger

## Session Continuity

Last session: 2026-03-12
Stopped at: Completed 02-01-PLAN.md (CoinGecko ingest + features + labels — Phase 2 Plan 1 complete)
Resume file: None
