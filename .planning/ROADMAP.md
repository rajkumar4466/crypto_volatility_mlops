# Roadmap: Crypto Volatility MLOps

## Overview

Seven phases, each delivering one independently verifiable layer of the MLOps stack. The build order is dictated by hard dependencies: infrastructure must exist before application code runs; the feature store must be populated before training can pull point-in-time features; training must produce a model before serving can load it; all components must work in isolation before Airflow wraps them into a DAG; the DAG must be running before monitoring has predictions to measure; CI/CD is added last once the Docker image is stable. Each phase is verified standalone before the next begins.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Infrastructure Foundation** - All AWS resources provisioned via Terraform with billing safeguards (completed 2026-03-12)
- [ ] **Phase 2: Data and Feature Pipeline** - Live CoinGecko ingest, 12-feature engineering, Feast feature store populated
- [ ] **Phase 3: Model Training and Registry** - XGBoost training, ONNX export, W&B tracking, automated promotion gate
- [ ] **Phase 4: Lambda Serving and API** - FastAPI + ONNX Runtime on Lambda with API Gateway endpoints
- [ ] **Phase 5: Airflow DAG Orchestration** - 7-task DAG scheduling all verified components end-to-end
- [ ] **Phase 6: Monitoring and Drift Detection** - KS-test drift detection, rolling accuracy, SNS alerts, CloudWatch dashboard
- [ ] **Phase 7: CI/CD Pipeline** - GitHub Actions lint/test on PR, Docker build to ECR and Lambda deploy on merge

## Phase Details

### Phase 1: Infrastructure Foundation
**Goal**: All AWS resources exist as Terraform-managed code, billing is guarded, and the ephemeral spin-up/tear-down lifecycle is verified
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05
**Success Criteria** (what must be TRUE):
  1. `terraform apply` creates all required AWS resources (EC2, RDS, ElastiCache, Lambda stub, S3, ECR, API Gateway, SNS, CloudWatch) with no manual console steps
  2. A CloudWatch billing alarm fires (or is verifiably configured to fire) at the $1 threshold before any resource incurs cost
  3. `terraform destroy` removes all resources and a CLI audit confirms no orphaned resources remain
  4. `docker-compose up` brings up all components locally for development and testing
**Plans**: 2 plans

Plans:
- [ ] 01-01-PLAN.md -- Terraform modules (billing, network, storage, compute, serverless) + lifecycle scripts
- [ ] 01-02-PLAN.md -- docker-compose for local development environment

### Phase 2: Data and Feature Pipeline
**Goal**: BTC OHLCV data flows from CoinGecko through 12-feature engineering into Feast offline (S3) and online (Redis) stores with no look-ahead bias
**Depends on**: Phase 1
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, FEAT-01, FEAT-02, FEAT-03, FEAT-04
**Success Criteria** (what must be TRUE):
  1. Running the ingest script produces a Parquet file in S3 with raw OHLCV candles from CoinGecko (no API key)
  2. All 12 engineered features and VOLATILE/CALM labels exist in the Feast offline store (S3 Parquet), computable from a single `feast apply` + ingest run
  3. `feast materialize` populates the Redis online store and a spot-check query returns feature values matching the offline store
  4. A unit test asserts that labels at time T use only data from T+1 through T+30 (no look-ahead bias) and training split is time-ordered
**Plans**: 2 plans

Plans:
- [ ] 02-01-PLAN.md — CoinGecko ingest + 12-feature engineering + VOLATILE/CALM labeling (TDD: look-ahead bias tests)
- [ ] 02-02-PLAN.md — Feast feature view definitions (single source of truth), offline S3 store population, Redis materialization

### Phase 3: Model Training and Registry
**Goal**: XGBoost trains on Feast offline features, exports to ONNX, logs to W&B, and only promotes to S3 registry if metrics improve over the current champion
**Depends on**: Phase 2
**Requirements**: TRAIN-01, TRAIN-02, TRAIN-03, TRAIN-04, TRAIN-05, REG-01, REG-02, REG-03
**Success Criteria** (what must be TRUE):
  1. Running the training script produces a W&B run with logged params, metrics (accuracy, F1, ROC-AUC), and feature importances visible in the W&B dashboard
  2. An ONNX model file is written to S3 only after passing a smoke test: load the exported model, run inference on a known input, assert output shape matches expected
  3. When a new model's F1 exceeds the current `current_metrics.json` champion, `current.onnx` is replaced and the promotion decision is logged; when it does not, the challenger is archived and `current.onnx` is unchanged
  4. An S3 JSON backup of run metrics exists at `runs/{run_id}/metrics.json` and `params.json`
**Plans**: 2 plans

Plans:
- [ ] 03-01-PLAN.md — XGBoost GridSearchCV training + ONNX export + post-export smoke test (TRAIN-01, TRAIN-02, TRAIN-03)
- [ ] 03-02-PLAN.md — W&B experiment tracking + S3 metrics backup + S3 model registry + automated promotion gate (TRAIN-04, TRAIN-05, REG-01, REG-02, REG-03)

### Phase 4: Lambda Serving and API
**Goal**: A live API endpoint returns BTC volatility predictions by reading features from Redis and running ONNX inference, with predictions logged for accuracy tracking
**Depends on**: Phase 3
**Requirements**: SERV-01, SERV-02, SERV-03, SERV-04, SERV-05
**Success Criteria** (what must be TRUE):
  1. `GET /health` returns 200 from the API Gateway URL
  2. `GET /predict` returns a JSON response with prediction (VOLATILE or CALM), probability, and model_version — sourced from Feast Redis, not inline feature computation
  3. Each prediction is logged to DynamoDB with timestamp, features, prediction, probability, and model_version
  4. 30 minutes after a prediction, the actual label is backfilled into DynamoDB for accuracy tracking
**Plans**: TBD

Plans:
- [ ] 04-01: FastAPI + ONNX Runtime Lambda container + API Gateway + Feast Redis integration + DynamoDB prediction logging + backfill job

### Phase 5: Airflow DAG Orchestration
**Goal**: A single Airflow DAG runs every 30 minutes, executing the verified ingest → features → predict → retrain → evaluate → promote → monitor sequence with retries and failure handling
**Depends on**: Phase 4
**Requirements**: ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05
**Success Criteria** (what must be TRUE):
  1. The Airflow web UI is accessible on port 8080 and shows the DAG with all 7 tasks and their dependency graph
  2. A manual DAG trigger completes all 7 tasks successfully end-to-end, with each task's logs showing expected output
  3. When the ingest task is forced to fail, the retrain task is automatically skipped (not failed); when evaluate fails, promote is skipped
  4. The DAG runs automatically on the 30-minute schedule without manual intervention
**Plans**: TBD

Plans:
- [ ] 05-01: Airflow on EC2 + RDS PostgreSQL setup + 7-task DAG with dependency enforcement and 30-minute schedule

### Phase 6: Monitoring and Drift Detection
**Goal**: Feature drift and model accuracy degradation are detected automatically, trigger alerts, and are visible on a CloudWatch dashboard — completing the Continuous Training loop
**Depends on**: Phase 5
**Requirements**: MON-01, MON-02, MON-03, MON-04, MON-05, MON-06
**Success Criteria** (what must be TRUE):
  1. The monitor Airflow task runs KS-test on recent vs reference feature distributions and logs a drift_score metric to CloudWatch; an artificially drifted dataset triggers the alert condition
  2. Rolling accuracy computed from backfilled actuals appears in CloudWatch as a `rolling_accuracy` metric updated each DAG cycle
  3. An SNS email is received within minutes when drift is detected or accuracy drops below 55%
  4. The CloudWatch dashboard displays rolling_accuracy, drift_score, model_version, prediction_latency, and retrain_count over time
  5. A detected drift event triggers an Airflow DAG run via the Airflow REST API (drift → retrain loop is observable end-to-end)
**Plans**: TBD

Plans:
- [ ] 06-01: KS-test drift detection + rolling accuracy computation + CloudWatch custom metrics + SNS alerts + drift-triggered retraining via Airflow REST API
- [ ] 06-02: CloudWatch dashboard with all metrics over time

### Phase 7: CI/CD Pipeline
**Goal**: Every PR runs lint and tests automatically; every merge to main builds a Docker image, pushes to ECR, and deploys to Lambda with a smoke test
**Depends on**: Phase 6
**Requirements**: CICD-01, CICD-02, CICD-03
**Success Criteria** (what must be TRUE):
  1. Opening a PR triggers a GitHub Actions CI run that executes ruff lint and pytest; a lint failure or test failure blocks merge
  2. Merging to main triggers a GitHub Actions CD run that builds a Docker image, pushes to ECR (with provenance: false), and applies Terraform to update the Lambda function
  3. The CD workflow ends with a smoke test hitting `GET /health` and `GET /predict` and failing the workflow if either returns non-200
**Plans**: TBD

Plans:
- [ ] 07-01: GitHub Actions CI workflow (lint + test on PR) + CD workflow (Docker build → ECR → Lambda deploy → smoke test)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure Foundation | 2/2 | Complete   | 2026-03-12 |
| 2. Data and Feature Pipeline | 0/2 | Not started | - |
| 3. Model Training and Registry | 0/2 | Not started | - |
| 4. Lambda Serving and API | 0/1 | Not started | - |
| 5. Airflow DAG Orchestration | 0/1 | Not started | - |
| 6. Monitoring and Drift Detection | 0/2 | Not started | - |
| 7. CI/CD Pipeline | 0/1 | Not started | - |
