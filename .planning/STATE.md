# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-12)

**Core value:** A working, observable MLOps loop where data drift triggers automated retraining, model evaluation, and promotion — all visible through dashboards and alerts within hours.
**Current focus:** Phase 1 — Infrastructure Foundation

## Current Position

Phase: 1 of 7 (Infrastructure Foundation)
Plan: 2 of 2 in current phase
Status: In progress
Last activity: 2026-03-12 — Plan 01-02 complete: docker-compose.yml for local dev environment

Progress: [█░░░░░░░░░] 7%

## Performance Metrics

**Velocity:**
- Total plans completed: 1
- Average duration: ~1 min
- Total execution time: ~1 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-infrastructure-foundation | 1 | ~1 min | ~1 min |

**Recent Trend:**
- Last 5 plans: 01-02 (1 min)
- Trend: N/A (first plan)

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

### Pending Todos

None yet.

### Blockers/Concerns

- ElastiCache free tier: only available for AWS accounts created before July 15, 2025 — verify account creation date before Phase 1
- Phase 2 (Feast): `feast apply` schema migration behavior and `feast materialize_incremental` timing have MEDIUM confidence — validate against Feast 0.61.0 changelog during planning
- Phase 4 (Lambda VPC): Lambda VPC subnet/security group config for ElastiCache access is a known complexity point — research flags this for deeper investigation during Phase 4 planning
- Phase 6 (drift thresholds): KS-test 0.01 p-value and "2+ features" rule are community estimates — backtest against historical BTC data before wiring to retrain trigger

## Session Continuity

Last session: 2026-03-12
Stopped at: Completed 01-02-PLAN.md (docker-compose.yml for local dev environment)
Resume file: None
