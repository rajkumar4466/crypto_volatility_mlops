---
phase: 05-airflow-dag-orchestration
plan: "01"
subsystem: infra
tags: [airflow, dag, orchestration, systemd, postgresql, python, mlops]

# Dependency graph
requires:
  - phase: 04-lambda-serving-and-api
    provides: serving Lambda, predict endpoint, backfill Lambda
  - phase: 03-model-training-and-registry
    provides: scripts/retrain.py, scripts/evaluate.py, scripts/promote.py
  - phase: 02-data-and-feature-pipeline
    provides: scripts/ingest.py, scripts/compute_features.py
  - phase: 01-infrastructure-foundation
    provides: EC2 instance (INFRA-01), RDS PostgreSQL (INFRA-02), swap config

provides:
  - Idempotent Airflow 2.10.4 install script with RDS init and systemd registration
  - 7-task DAG (crypto_volatility_pipeline) with skip-enforcement trigger rules
  - Systemd service units for airflow-webserver and airflow-scheduler
  - Environment variable template for Airflow configuration

affects:
  - 06-drift-detection-and-retraining
  - 07-observability-and-alerting

# Tech tracking
tech-stack:
  added: [apache-airflow==2.10.4, apache-airflow[postgres], psycopg2, functools.partial]
  patterns: [thin subprocess wrapper DAG, trigger_rule skip enforcement, idempotent setup scripts, systemd EnvironmentFile]

key-files:
  created:
    - scripts/airflow_setup.sh
    - dags/crypto_volatility_dag.py
    - infra/airflow/airflow-webserver.service
    - infra/airflow/airflow-scheduler.service
    - infra/airflow/airflow.env.template
  modified: []

key-decisions:
  - "Airflow 2.10.4 (latest 2.10.x) installed with constraint file — prevents pip dependency hell on shared EC2 instance"
  - "TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS on retrain and promote — skips on upstream hard-failure but runs if upstream was merely skipped"
  - "TriggerRule.ALL_DONE on monitor — always emits observability signals even when pipeline partially fails"
  - "LocalExecutor with RDS PostgreSQL backend — matches t3.micro RAM constraint (no Celery workers, no broker)"
  - "DB_PASS/RDS_ENDPOINT/AIRFLOW_ADMIN_PASSWORD accepted as env vars or positional args — no hardcoded credentials"
  - "run_script() + functools.partial pattern — keeps DAG as thin orchestration layer, all business logic stays in Phase 1-4 scripts"
  - "max_active_runs=1 — prevents concurrent DAG runs fighting over shared Feast materialization and model registry state"
  - "airflow.env written with chmod 600 under airflow user — env file contains DB password"

patterns-established:
  - "Thin subprocess wrapper: DAG calls sys.executable + script_path, script handles all logic. Failure = non-zero exit code."
  - "Trigger rule skip enforcement: NONE_FAILED_MIN_ONE_SUCCESS at retrain and promote creates resilient pipeline that distinguishes skip from failure"
  - "Idempotent setup: createdb ignores already-exists, airflow users create uses || true, systemctl enable is idempotent"

requirements-completed: [ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05]

# Metrics
duration: 8min
completed: 2026-03-13
---

# Phase 5 Plan 01: Airflow DAG Orchestration Summary

**Airflow 2.10.4 idempotent install script + 7-task DAG with TriggerRule skip enforcement wiring all Phase 1-4 scripts on a 30-minute schedule via systemd-managed LocalExecutor**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-13T15:50:08Z
- **Completed:** 2026-03-13T15:58:00Z
- **Tasks:** 2 of 3 automated (Task 3 is human-verify checkpoint)
- **Files created:** 5

## Accomplishments

- `scripts/airflow_setup.sh`: fully idempotent install — pre-flight swap/Python checks, pip constraints install, RDS connectivity verify, `airflow db migrate`, admin user creation, DAG deploy, systemd enable/start
- `dags/crypto_volatility_dag.py`: 7-task DAG with correct trigger rule design — retrain and promote use `NONE_FAILED_MIN_ONE_SUCCESS` (orange skip, not red fail, when upstream fails), monitor uses `ALL_DONE` for guaranteed observability
- `infra/airflow/airflow.env.template` + two systemd unit files for webserver (port 8080) and scheduler

## Task Commits

Each task was committed atomically:

1. **Task 1: Airflow Installation Script + Systemd Service Files** - `8962849` (feat)
2. **Task 2: 7-Task DAG with Trigger Rule Skip Enforcement** - `0ba0ec3` (feat)
3. **Task 3: Human Verification** - awaiting human verification (checkpoint)

## Files Created/Modified

- `scripts/airflow_setup.sh` — Idempotent Airflow 2.10.4 install: pre-flight checks, pip constraints, RDS init, airflow db migrate, admin user, DAG deploy, systemd registration
- `dags/crypto_volatility_dag.py` — 7-task pipeline DAG: ingest → compute_features → predict → retrain → evaluate → promote → monitor with trigger_rule skip enforcement
- `infra/airflow/airflow.env.template` — Environment variable template with all AIRFLOW__ config vars and ${PLACEHOLDER} values
- `infra/airflow/airflow-webserver.service` — Systemd unit, ExecStart=/usr/local/bin/airflow webserver --port 8080, EnvironmentFile=/opt/airflow/airflow.env
- `infra/airflow/airflow-scheduler.service` — Systemd unit for Airflow scheduler

## Decisions Made

- **Airflow 2.10.4 with constraint file:** The constraint URL (`constraints-2.10.4/constraints-3.11.txt`) pins all transitive dependencies to a tested combination. Plain `pip install apache-airflow` on a shared EC2 instance risks dependency conflicts with existing packages.
- **TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS on retrain/promote:** This is the Airflow 2.x replacement for the deprecated `all_success` behavior with skips. When ingest fails, compute_features→predict are skipped (orange), and retrain should also be skipped (orange) — not failed (red). Without this rule, retrain would fail on skipped upstream.
- **TriggerRule.ALL_DONE on monitor:** Monitor must emit metrics and alerts even when the pipeline fails. This is the observability task; silencing it on failure is the opposite of what monitoring is for.
- **LocalExecutor + RDS PostgreSQL:** Matches the t3.micro RAM constraint from Phase 1 decisions. No Celery, no Redis broker needed.
- **max_active_runs=1:** BTC features are computed incrementally — two concurrent runs would race on Feast materialization and the champion model file.
- **run_script() + functools.partial:** Keeps the DAG as pure orchestration. All business logic (error handling, feature computation, model evaluation) stays in Phase 1-4 scripts. The DAG only cares about exit codes.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- Task 2 verification: the plan's verification script uses single-quoted grep (`schedule_interval='*/30 * * * *'`) but Python style guides and this codebase use double quotes. Used `grep -E` with `['\"]` character class to match both — the actual schedule value is correct.

## User Setup Required

**Manual deployment required before Task 3 checkpoint can be verified.**

To deploy:
```bash
# SSH into EC2 instance
export DB_PASS="<your-rds-password>"
export RDS_ENDPOINT="<your-rds-endpoint>"
export AIRFLOW_ADMIN_PASSWORD="<your-admin-password>"
bash scripts/airflow_setup.sh
```

Then verify at: http://<EC2-public-IP>:8080

See Task 3 checkpoint for complete verification steps (UI access, manual trigger, skip behavior, schedule verification).

## Next Phase Readiness

- All orchestration artifacts ready for EC2 deployment
- Task 3 (human-verify checkpoint) pending — requires running EC2 instance with RDS from Phase 1 infrastructure
- Phase 6 (drift detection) depends on monitor.py emitting drift signals — the monitor task in this DAG is the trigger point
- No blockers for Phase 6 planning; deployment can proceed in parallel

---
*Phase: 05-airflow-dag-orchestration*
*Completed: 2026-03-13*

## Self-Check: PASSED

All created files verified on disk. All task commits verified in git history.
