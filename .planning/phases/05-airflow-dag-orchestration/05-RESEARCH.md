# Phase 5: Airflow DAG Orchestration - Research

**Researched:** 2026-03-12
**Domain:** Apache Airflow orchestration on EC2/RDS, DAG task dependency management
**Confidence:** HIGH (official docs + verified web sources)

## Summary

Phase 5 wraps all verified components from Phases 1-4 into a single Apache Airflow DAG that runs every 30 minutes. The core challenge is not writing Python scripts — those already exist from earlier phases — but wiring them together with proper dependency enforcement so that downstream tasks are *skipped* (not failed) when upstream tasks fail.

Apache Airflow has moved to 3.x as the current stable release (3.1.8 as of March 2026). However, Airflow 3.x introduced significant breaking changes in its API, task execution model, and configuration. For a t3.micro deployment against an established Python 3.11 environment, **Airflow 2.10.x** (the last stable 2.x series) is the recommended choice: it is well-documented, has mature systemd deployment patterns for EC2, and avoids migration risk on a constrained instance. The project infrastructure was designed with Airflow 2.x patterns (ORCH-01 through ORCH-05 reference standalone EC2 + RDS PostgreSQL, which matches 2.x deployment).

The primary risk on a t3.micro (1 GB RAM) is memory exhaustion during Airflow installation and at runtime. EC2 swap (4 GB) is already required by INFRA-02 — this is non-negotiable and must be in place before Airflow starts. The webserver + scheduler together consume ~400-600 MB, leaving little headroom; avoiding CeleryExecutor and using LocalExecutor with PostgreSQL is the correct pattern for this scale.

**Primary recommendation:** Install Airflow 2.10.x with LocalExecutor + RDS PostgreSQL, deploy webserver and scheduler as systemd services, write the 7-task DAG using PythonOperator with explicit `trigger_rule` settings to implement the skip-on-failure requirement.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ORCH-01 | Apache Airflow on EC2 t3.micro with RDS db.t3.micro PostgreSQL metadata store | Installation section: pip install with constraints, airflow.cfg sql_alchemy_conn, LocalExecutor |
| ORCH-02 | DAG with 7 tasks: ingest → compute_features → predict → retrain → evaluate → promote → monitor | DAG structure section: PythonOperator chain, dependency syntax |
| ORCH-03 | Task dependencies enforced: retrain skips if ingest fails, promote skips if evaluate fails | Trigger rules section: `trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS` on retrain; `trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS` on promote |
| ORCH-04 | DAG scheduled every 30 minutes | Schedule section: `schedule_interval='*/30 * * * *'` or `timedelta(minutes=30)` |
| ORCH-05 | Airflow webserver accessible on port 8080 for UI monitoring | Systemd + EC2 security group section |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| apache-airflow | 2.10.x | DAG orchestration runtime | Last stable 2.x; well-documented EC2 patterns; avoids 3.x breaking changes |
| apache-airflow[postgres] | same | psycopg2 driver for PostgreSQL metadata | Required extra for RDS PostgreSQL backend |
| psycopg2-binary | >=2.9 | PostgreSQL adapter | Bundled with postgres extra; binary avoids libpq-dev dependency |
| Python | 3.11 | Runtime | Project-wide requirement; supported by Airflow 2.10.x |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| systemd service files | N/A | Process supervision | Required for boot-persistence on EC2; prevent manual restarts |
| boto3 | Latest | AWS SDK for Airflow tasks calling S3/Lambda/DynamoDB | Tasks that call existing Phase 1-4 scripts |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| LocalExecutor | CeleryExecutor | Celery requires Redis/RabbitMQ broker — overkill for single-node t3.micro |
| Airflow 2.10.x | Airflow 3.1.x | 3.x is current stable but breaking API changes and early-maturity risk on constrained EC2 |
| Systemd services | Docker Compose | Docker on t3.micro adds memory overhead; systemd is lighter and simpler |

**Installation:**
```bash
# CRITICAL: swap must already be active (INFRA-02) before running pip install
# Airflow uses pip constraints for reproducible installs
AIRFLOW_VERSION=2.10.4
PYTHON_VERSION=3.11
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

pip install "apache-airflow[postgres]==${AIRFLOW_VERSION}" \
  --constraint "${CONSTRAINT_URL}"
```

## Architecture Patterns

### Recommended Project Structure
```
dags/
└── crypto_volatility_dag.py    # Single DAG file with all 7 tasks

scripts/                         # Existing Phase 1-4 scripts called by tasks
├── ingest.py
├── compute_features.py
├── predict.py
├── retrain.py
├── evaluate.py
├── promote.py
└── monitor.py
```

### Pattern 1: LocalExecutor + RDS PostgreSQL
**What:** Airflow runs webserver and scheduler in two systemd services on the same EC2 host; tasks execute as subprocesses (LocalExecutor); metadata (DAG state, task instances, logs) stored in RDS PostgreSQL.
**When to use:** Single-node deployment, < 10 concurrent tasks, cost-sensitive.
**airflow.cfg key settings:**
```ini
[core]
executor = LocalExecutor
sql_alchemy_conn = postgresql+psycopg2://airflow:<password>@<rds-endpoint>:5432/airflow

[webserver]
web_server_port = 8080
```

### Pattern 2: 7-Task DAG with Trigger Rules for Skip Propagation
**What:** The required dependency chain `ingest >> compute_features >> predict >> retrain >> evaluate >> promote >> monitor` with skip behavior when upstream fails.

**The core skip problem:** By default (`trigger_rule=ALL_SUCCESS`), if `ingest` fails, all downstream tasks become `upstream_failed` — not `skipped`. For the requirement that `retrain` is *skipped* (not failed) when `ingest` fails, the trigger rule must be changed on specific tasks.

**Correct trigger rule strategy:**
```
ingest                           (default: ALL_SUCCESS)
  >> compute_features             (default: ALL_SUCCESS — skip if ingest fails, which is correct)
  >> predict                      (default: ALL_SUCCESS)
  >> retrain                      (trigger_rule=NONE_FAILED_MIN_ONE_SUCCESS)
  >> evaluate                     (default: ALL_SUCCESS)
  >> promote                      (trigger_rule=NONE_FAILED_MIN_ONE_SUCCESS)
  >> monitor                      (trigger_rule=ALL_DONE — always runs for observability)
```

**Note on ORCH-03 exact requirement:** "retrain skips if ingest fails" — with `trigger_rule=NONE_FAILED_MIN_ONE_SUCCESS` (Airflow 2.2+), the task skips when all upstream tasks are either skipped or at least one failed. This matches the requirement. `predict` with default `ALL_SUCCESS` will already be skipped if `compute_features` fails.

**DAG structure:**
```python
# Source: Apache Airflow official docs + Astronomer trigger rules guide
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule
from datetime import datetime, timedelta
import subprocess

default_args = {
    'owner': 'airflow',
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'start_date': datetime(2026, 1, 1),
}

with DAG(
    dag_id='crypto_volatility_pipeline',
    default_args=default_args,
    schedule_interval='*/30 * * * *',
    catchup=False,
    max_active_runs=1,
) as dag:

    ingest = PythonOperator(
        task_id='ingest',
        python_callable=run_ingest,
    )
    compute_features = PythonOperator(
        task_id='compute_features',
        python_callable=run_compute_features,
    )
    predict = PythonOperator(
        task_id='predict',
        python_callable=run_predict,
    )
    retrain = PythonOperator(
        task_id='retrain',
        python_callable=run_retrain,
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    )
    evaluate = PythonOperator(
        task_id='evaluate',
        python_callable=run_evaluate,
    )
    promote = PythonOperator(
        task_id='promote',
        python_callable=run_promote,
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    )
    monitor = PythonOperator(
        task_id='monitor',
        python_callable=run_monitor,
        trigger_rule=TriggerRule.ALL_DONE,
    )

    ingest >> compute_features >> predict >> retrain >> evaluate >> promote >> monitor
```

### Pattern 3: Systemd Service Deployment
**What:** Two systemd unit files ensure webserver and scheduler auto-restart on crash/reboot.
**Files:** `/etc/systemd/system/airflow-webserver.service` and `/etc/systemd/system/airflow-scheduler.service`
```ini
[Unit]
Description=Airflow webserver daemon
After=network.target postgresql.service

[Service]
EnvironmentFile=/etc/airflow/airflow.env
User=airflow
Group=airflow
Type=simple
ExecStart=/home/airflow/airflow-venv/bin/airflow webserver --port 8080
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

### Anti-Patterns to Avoid
- **Using SQLite as metadata DB:** No parallelism even with LocalExecutor; forbidden by requirements
- **CeleryExecutor on t3.micro:** Needs Redis/RabbitMQ broker, 3+ processes, will OOM
- **`catchup=True` on 30-minute DAG:** If EC2 restarts, Airflow will backfill months of runs; always `catchup=False`
- **`max_active_runs` unset:** Multiple concurrent runs of same DAG will fight over shared state; set `max_active_runs=1`
- **Default `ALL_SUCCESS` on retrain:** Will mark retrain as `upstream_failed` not `skipped` — violates ORCH-03
- **Installing Airflow without constraints file:** Known to produce dependency conflicts; always use constraint URL

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Skip-on-failure dependency | Custom Python skip logic | `TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS` | Built-in; tested against all edge cases |
| Task retries | Custom retry loops | `retries` + `retry_delay` in `default_args` | Airflow handles exponential backoff, state tracking |
| DAG scheduling | Custom cron + cron daemon | `schedule_interval='*/30 * * * *'` | Airflow scheduler handles missed runs, backfill, overlap prevention |
| Process supervision | Custom shell watchdog | systemd `Restart=on-failure` | OS-level process management; handles OOM kills and reboots |

**Key insight:** All business logic already exists in Phase 1-4 scripts. Airflow tasks should be thin wrappers (`subprocess.run` or direct Python calls) — the DAG is wiring, not re-implementation.

## Common Pitfalls

### Pitfall 1: OOM on t3.micro During Airflow Install
**What goes wrong:** `pip install apache-airflow` resolves hundreds of dependencies; peak RSS during resolution exceeds 1 GB, causing OOM kill.
**Why it happens:** t3.micro has 1 GB RAM; pip dependency resolution is memory-intensive.
**How to avoid:** Ensure 4 GB swap is active (INFRA-02) before `pip install`. Verify with `free -h` before running pip.
**Warning signs:** pip install hangs > 5 minutes then exits 137 (OOM killed).

### Pitfall 2: `upstream_failed` Instead of `skipped`
**What goes wrong:** When `ingest` fails, `retrain` shows as `upstream_failed` in the UI, not `skipped`.
**Why it happens:** Default `trigger_rule=ALL_SUCCESS` propagates failure state, not skip state.
**How to avoid:** Set `trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS` on `retrain` and `promote`. Verify by force-failing `ingest` and checking that `retrain` shows orange (skipped), not red (failed).
**Warning signs:** Success criteria 3 fails in verification: "retrain is automatically skipped" not met.

### Pitfall 3: `catchup=True` Backfill Storm
**What goes wrong:** After EC2 restart with a stale `start_date`, Airflow schedules hundreds of historical runs.
**Why it happens:** `catchup=True` is the default in many Airflow versions.
**How to avoid:** Always set `catchup=False` on the DAG. Set `start_date` to a recent date (not far in the past).
**Warning signs:** Airflow UI shows 100s of DAG runs queued immediately after startup.

### Pitfall 4: RDS PostgreSQL Not Reachable at Airflow Init
**What goes wrong:** `airflow db migrate` fails with connection refused.
**Why it happens:** EC2 security group for RDS only allows traffic from a specific source; or RDS endpoint not yet available.
**How to avoid:** Verify RDS is accessible from EC2 before running `airflow db migrate`: `psql -h <rds-endpoint> -U airflow -d airflow`. Ensure EC2's security group is in the RDS inbound rules.
**Warning signs:** `FATAL: password authentication failed` or `could not connect to server`.

### Pitfall 5: Port 8080 Blocked
**What goes wrong:** Browser cannot reach Airflow UI at `http://<ec2-public-ip>:8080`.
**Why it happens:** EC2 security group does not allow inbound TCP 8080.
**How to avoid:** Add inbound rule in EC2 security group: `Custom TCP, port 8080, source 0.0.0.0/0` (or restrict to your IP).
**Warning signs:** Browser shows "Connection refused" or timeout.

### Pitfall 6: Airflow 2.x vs 3.x API Incompatibility
**What goes wrong:** Stack Overflow examples using `from airflow.operators.python_operator import PythonOperator` (Airflow 1.x) fail on 2.x. Airflow 3.x changes task lifecycle/API further.
**Why it happens:** Import paths changed in 2.0; 3.x adds more breaking changes.
**How to avoid:** Use Airflow 2.x import paths: `from airflow.operators.python import PythonOperator`. Pin to 2.10.x with constraints.
**Warning signs:** `ImportError: cannot import name 'PythonOperator' from 'airflow.operators.python_operator'`

## Code Examples

### Airflow DB Initialization with RDS
```bash
# Source: Apache Airflow official docs (airflow.apache.org/docs/apache-airflow/2.x)
export AIRFLOW_HOME=/opt/airflow
export AIRFLOW__CORE__SQL_ALCHEMY_CONN="postgresql+psycopg2://airflow:${DB_PASS}@${RDS_ENDPOINT}:5432/airflow"
export AIRFLOW__CORE__EXECUTOR=LocalExecutor
export AIRFLOW__WEBSERVER__WEB_SERVER_PORT=8080

airflow db migrate
airflow users create \
  --username admin \
  --password admin \
  --firstname Admin \
  --lastname User \
  --role Admin \
  --email admin@example.com
```

### DAG Force-Fail Test (for ORCH-03 verification)
```python
# In the DAG, temporarily override ingest to raise an exception:
def run_ingest_fail(**kwargs):
    raise Exception("Simulated ingest failure for ORCH-03 test")
```

### Task Callable Pattern (thin wrapper)
```python
import subprocess, sys

def run_ingest(**kwargs):
    result = subprocess.run(
        [sys.executable, '/opt/airflow/scripts/ingest.py'],
        capture_output=True, text=True, check=True
    )
    print(result.stdout)

def run_retrain(**kwargs):
    result = subprocess.run(
        [sys.executable, '/opt/airflow/scripts/retrain.py'],
        capture_output=True, text=True, check=True
    )
    print(result.stdout)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `PythonOperator` from `airflow.operators.python_operator` | `airflow.operators.python` | Airflow 2.0 | Old import path broken in 2.x |
| `schedule_interval` parameter | `schedule` parameter (Airflow 2.4+) | Airflow 2.4 | `schedule_interval` deprecated but still works in 2.10 |
| SQLite default metadata | PostgreSQL required for LocalExecutor | Historical | SQLite has no concurrent write support |
| Airflow 2.x as stable | Airflow 3.x is now stable (3.1.8) | Early 2025 | Use 2.10.x to avoid 3.x breaking changes for this project |

**Deprecated/outdated:**
- `airflow initdb`: Replaced by `airflow db migrate` in 2.x
- `SequentialExecutor`: Replaced by `LocalExecutor` for single-node parallel execution
- `CeleryExecutor` for single-node: Overkill; LocalExecutor sufficient

## Open Questions

1. **Airflow 2.10.x exact latest patch version**
   - What we know: 2.10.x series is the last stable 2.x line before 3.0
   - What's unclear: Exact patch version (2.10.3? 2.10.4?) — check PyPI at install time
   - Recommendation: Use `apache-airflow==2.10.*` and lock to exact version found

2. **AIRFLOW_HOME path on EC2**
   - What we know: Default is `~/airflow`; production typically uses `/opt/airflow`
   - What's unclear: Does Terraform user-data set this up, or does Airflow plan own it?
   - Recommendation: Plan should create `/opt/airflow`, set `AIRFLOW_HOME` in `/etc/environment`

3. **RDS PostgreSQL database pre-creation**
   - What we know: `airflow db migrate` requires the `airflow` database to exist in RDS
   - What's unclear: Does Phase 1 Terraform create the `airflow` database in RDS or just the RDS instance?
   - Recommendation: Plan must include `createdb` step against RDS if database doesn't exist

## Sources

### Primary (HIGH confidence)
- Apache Airflow official docs (airflow.apache.org/docs/apache-airflow/stable) — trigger rules, scheduling, installation
- Apache Airflow PyPI page — version/constraints information
- Astronomer.io docs (astronomer.io/docs/learn/airflow-trigger-rules) — trigger rule behavior, NONE_FAILED_MIN_ONE_SUCCESS

### Secondary (MEDIUM confidence)
- Medium/blog posts on EC2 systemd deployment — verified against official docs patterns
- sparkcodehub.com Airflow guides — cross-referenced with official docs

### Tertiary (LOW confidence)
- None — all critical claims verified with official sources or multiple cross-referenced guides

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified against official Airflow PyPI, official docs
- Architecture: HIGH — LocalExecutor + PostgreSQL is the documented single-node pattern
- Trigger rules: HIGH — verified against Astronomer docs (official Airflow partner) and official docs
- Pitfalls: MEDIUM — EC2 memory constraints from multiple installation guides; swap requirement already in INFRA-02

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (30 days — Airflow 2.10.x is stable, unlikely to change)
