# Requirements: Crypto Volatility MLOps

**Defined:** 2026-03-12
**Core Value:** A working, observable MLOps loop where data drift triggers automated retraining, model evaluation, and promotion — all visible through dashboards and alerts within hours.

## v1 Requirements

### Infrastructure

- [x] **INFRA-01**: All AWS resources provisioned via Terraform (ECR, EC2, RDS, ElastiCache, Lambda, API Gateway, S3, DynamoDB, SNS, CloudWatch)
- [x] **INFRA-02**: EC2 user-data script configures 2-4GB swap before Airflow starts
- [x] **INFRA-03**: CloudWatch billing alarm triggers at $1 threshold before any resource creation
- [x] **INFRA-04**: docker-compose.yml for local development and testing of all components
- [x] **INFRA-05**: Destroy script (terraform destroy + cleanup of manually-created resources like snapshots, Elastic IPs)

### Data Pipeline

- [x] **DATA-01**: Ingest BTC 1-minute OHLCV candles from CoinGecko free API (no API key)
- [x] **DATA-02**: Compute 12 engineered features: volatility_10m, volatility_30m, volatility_ratio, rsi_14, volume_spike, volume_trend, price_range_30m, sma_10_vs_sma_30, max_drawdown_30m, candle_body_avg, hour_of_day, day_of_week
- [x] **DATA-03**: Label each sample: VOLATILE (>2% swing in next 30 min) or CALM
- [x] **DATA-04**: Time-ordered train/test split (no shuffle) to prevent look-ahead bias

### Feature Store

- [x] **FEAT-01**: Feast feature definitions for all 12 features (single source of truth)
- [x] **FEAT-02**: S3 offline store for historical features (Parquet, used by training)
- [x] **FEAT-03**: Redis online store via ElastiCache t3.micro (used by serving)
- [x] **FEAT-04**: Feature computation happens once in ingest, written to both stores — no duplication in training or serving code

### Model Training

- [ ] **TRAIN-01**: XGBoost classifier with GridSearchCV (cross-validated hyperparameter tuning)
- [ ] **TRAIN-02**: Export trained model to ONNX via onnxmltools (export best_estimator_, not GridSearchCV wrapper)
- [ ] **TRAIN-03**: ONNX validation step: load exported model, run inference, assert output shape before writing to S3
- [ ] **TRAIN-04**: W&B experiment tracking: log params, metrics (accuracy, F1, ROC-AUC), feature importance, model artifact
- [ ] **TRAIN-05**: S3 JSON backup of run metrics (runs/{run_id}/metrics.json, params.json)

### Model Registry

- [ ] **REG-01**: S3 versioned model storage: models/current.onnx (production) + models/v{n}.onnx (archived)
- [ ] **REG-02**: Promotion gate: new model replaces current.onnx only if F1 score exceeds current production model
- [ ] **REG-03**: Promotion decision logged to W&B and S3 (promoted/rejected, old vs new metrics)

### Serving

- [ ] **SERV-01**: Lambda function with ONNX Runtime for inference (x86_64 architecture, not ARM64)
- [ ] **SERV-02**: FastAPI handler: reads features from Redis (Feast online store), runs ONNX inference, returns prediction
- [ ] **SERV-03**: API Gateway HTTP API: GET /predict (latest prediction), GET /health
- [ ] **SERV-04**: Prediction logging to DynamoDB: timestamp, features, prediction, probability, model_version
- [ ] **SERV-05**: Backfill actual labels 30 minutes after prediction for accuracy tracking

### Orchestration

- [ ] **ORCH-01**: Apache Airflow on EC2 t3.micro with RDS db.t3.micro PostgreSQL metadata store
- [ ] **ORCH-02**: DAG with 7 tasks: ingest → compute_features → predict → retrain → evaluate → promote → monitor
- [ ] **ORCH-03**: Task dependencies enforced: retrain skips if ingest fails, promote skips if evaluate fails
- [ ] **ORCH-04**: DAG scheduled every 30 minutes
- [ ] **ORCH-05**: Airflow webserver accessible on port 8080 for UI monitoring

### Monitoring

- [ ] **MON-01**: Data drift detection via scipy KS-test on feature distributions (training vs recent, p-value < 0.01)
- [ ] **MON-02**: Model drift detection via rolling accuracy on backfilled actuals (alert if accuracy < 55%)
- [ ] **MON-03**: CloudWatch custom metrics: rolling_accuracy, drift_score, model_version, prediction_latency, retrain_count
- [ ] **MON-04**: CloudWatch dashboard showing all metrics over time
- [ ] **MON-05**: SNS topic with email subscription for drift/accuracy/latency alerts
- [ ] **MON-06**: Drift-triggered retraining: SNS → Airflow REST API to trigger retrain DAG

### CI/CD

- [ ] **CICD-01**: GitHub Actions CI: lint (ruff) + pytest + smoke train on PR
- [ ] **CICD-02**: GitHub Actions CD: Docker build → push to ECR (with provenance: false) → terraform apply on merge
- [ ] **CICD-03**: Post-deploy smoke test: hit GET /health and GET /predict endpoints

## v2 Requirements

### Enhanced ML

- **ML-01**: Multi-coin support (ETH, SOL alongside BTC)
- **ML-02**: Ensemble models (XGBoost + LightGBM comparison)
- **ML-03**: Hyperparameter optimization with Optuna

### Enhanced Ops

- **OPS-01**: A/B testing with Lambda aliases (weighted routing)
- **OPS-02**: Canary deployment (10% traffic to new model)
- **OPS-03**: Grafana dashboard (richer than CloudWatch)
- **OPS-04**: PagerDuty integration for alerting

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real-time streaming (Kafka/Kinesis) | 5-min polling is adequate; streaming adds cost and complexity |
| GPU inference | XGBoost + ONNX on CPU is sufficient |
| Kubernetes / EKS | Lambda + EC2 covers this scale; K8s is overkill |
| Custom frontend dashboard | CloudWatch + W&B + Airflow UI are sufficient |
| LSTM / deep learning models | XGBoost trains in <2s; DL adds GPU dependency |
| Profitable trading strategy | This is an MLOps learning project, not a trading bot |
| MLflow server | W&B + S3 covers tracking without hosting overhead |
| Mobile app or notifications | Email via SNS is sufficient |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 — Infrastructure Foundation | Complete |
| INFRA-02 | Phase 1 — Infrastructure Foundation | Complete |
| INFRA-03 | Phase 1 — Infrastructure Foundation | Complete |
| INFRA-04 | Phase 1 — Infrastructure Foundation | Complete |
| INFRA-05 | Phase 1 — Infrastructure Foundation | Complete |
| DATA-01 | Phase 2 — Data and Feature Pipeline | Complete |
| DATA-02 | Phase 2 — Data and Feature Pipeline | Complete |
| DATA-03 | Phase 2 — Data and Feature Pipeline | Complete |
| DATA-04 | Phase 2 — Data and Feature Pipeline | Complete |
| FEAT-01 | Phase 2 — Data and Feature Pipeline | Complete |
| FEAT-02 | Phase 2 — Data and Feature Pipeline | Complete |
| FEAT-03 | Phase 2 — Data and Feature Pipeline | Complete |
| FEAT-04 | Phase 2 — Data and Feature Pipeline | Complete |
| TRAIN-01 | Phase 3 — Model Training and Registry | Pending |
| TRAIN-02 | Phase 3 — Model Training and Registry | Pending |
| TRAIN-03 | Phase 3 — Model Training and Registry | Pending |
| TRAIN-04 | Phase 3 — Model Training and Registry | Pending |
| TRAIN-05 | Phase 3 — Model Training and Registry | Pending |
| REG-01 | Phase 3 — Model Training and Registry | Pending |
| REG-02 | Phase 3 — Model Training and Registry | Pending |
| REG-03 | Phase 3 — Model Training and Registry | Pending |
| SERV-01 | Phase 4 — Lambda Serving and API | Pending |
| SERV-02 | Phase 4 — Lambda Serving and API | Pending |
| SERV-03 | Phase 4 — Lambda Serving and API | Pending |
| SERV-04 | Phase 4 — Lambda Serving and API | Pending |
| SERV-05 | Phase 4 — Lambda Serving and API | Pending |
| ORCH-01 | Phase 5 — Airflow DAG Orchestration | Pending |
| ORCH-02 | Phase 5 — Airflow DAG Orchestration | Pending |
| ORCH-03 | Phase 5 — Airflow DAG Orchestration | Pending |
| ORCH-04 | Phase 5 — Airflow DAG Orchestration | Pending |
| ORCH-05 | Phase 5 — Airflow DAG Orchestration | Pending |
| MON-01 | Phase 6 — Monitoring and Drift Detection | Pending |
| MON-02 | Phase 6 — Monitoring and Drift Detection | Pending |
| MON-03 | Phase 6 — Monitoring and Drift Detection | Pending |
| MON-04 | Phase 6 — Monitoring and Drift Detection | Pending |
| MON-05 | Phase 6 — Monitoring and Drift Detection | Pending |
| MON-06 | Phase 6 — Monitoring and Drift Detection | Pending |
| CICD-01 | Phase 7 — CI/CD Pipeline | Pending |
| CICD-02 | Phase 7 — CI/CD Pipeline | Pending |
| CICD-03 | Phase 7 — CI/CD Pipeline | Pending |

**Coverage:**
- v1 requirements: 39 total
- Mapped to phases: 39
- Unmapped: 0

---
*Requirements defined: 2026-03-12*
*Last updated: 2026-03-12 after roadmap creation*
