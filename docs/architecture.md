# System Architecture

## Overview

The crypto volatility MLOps pipeline runs entirely on AWS, orchestrated by Apache Airflow
on a single EC2 instance. The DAG (`crypto_volatility_pipeline`) executes every 30 minutes,
running 8 tasks in sequence.

## How EC2 is Used

EC2 (t3.small, 2 vCPU, 2GB RAM + 4GB swap) is the **central orchestration hub**. It runs:

- **Airflow Scheduler** — triggers the DAG every 30 minutes
- **Airflow Webserver** — UI on port 8080 for monitoring and manual triggers
- **All 8 DAG tasks** — each task runs as a subprocess on EC2 itself (no remote workers)

EC2 does ALL the compute-heavy work: data ingestion, feature engineering, Feast
materialization, model training (GridSearchCV + XGBoost), model evaluation, and monitoring.
Lambda only handles lightweight inference at serving time.

### Why EC2, not Lambda or ECS?

- Training requires 2+ GB RAM and runs for minutes — Lambda's 15-min/10GB limits are tight
- Airflow needs a persistent scheduler process — serverless doesn't fit
- Single t3.small is cheapest for this workload (~$15/month)

## DAG Pipeline (8 Tasks)

```
ingest -> compute_features -> materialize -> predict -> retrain -> evaluate -> promote -> monitor
```

### Task Details

| # | Task | Script | What it does | AWS Services Used |
|---|------|--------|-------------|-------------------|
| 1 | **ingest** | `scripts/ingest.py` | Fetches BTC/USDT 15-min candles from Binance API. First run backfills 90 days (~8,600 candles). Subsequent runs fetch latest 1,000. Writes raw Parquet to S3. | S3 (write) |
| 2 | **compute_features** | `scripts/compute_features.py` | Reads latest raw Parquet from S3. Computes 12 Binance-derived features + 3 sentiment features from Fear & Greed and CoinGecko APIs. Applies volatility labels. Writes to Feast offline store path on S3. | S3 (read/write) |
| 3 | **materialize** | `scripts/materialize.py` | Runs `feast materialize` to push features from S3 Parquet (offline store) to ElastiCache Redis (online store). Spot-checks Redis for null features. | S3 (read), Redis (write) |
| 4 | **predict** | `scripts/predict.py` | Calls the serving Lambda via API Gateway `GET /predict`. Lambda reads features from Redis, runs ONNX inference, writes prediction to DynamoDB. | API Gateway, Lambda |
| 5 | **retrain** | `scripts/retrain.py` | Runs `training/train.py`: pulls features from Feast offline store, GridSearchCV with TimeSeriesSplit, exports ONNX, smoke tests, logs to W&B, backs up to S3, runs champion/challenger promotion gate. | S3 (read/write), W&B (write) |
| 6 | **evaluate** | `scripts/evaluate.py` | Compares `challenger_metrics.json` vs `current_metrics.json` on S3. Logs whether challenger outperforms. | S3 (read) |
| 7 | **promote** | `scripts/promote.py` | If challenger F1 > champion F1, copies `challenger.onnx` -> `current.onnx` on S3. | S3 (read/write) |
| 8 | **monitor** | DAG inline (`run_monitor`) | Loads reference + recent features from S3. Runs KS-test drift detection. Computes rolling accuracy from DynamoDB. Publishes 5 CloudWatch metrics. Triggers retrain DAG if drift detected. | S3 (read), DynamoDB (read), CloudWatch (write), Airflow API |

### Trigger Rules

- Tasks 1-4, 6: **ALL_SUCCESS** — skip if any upstream fails
- Task 5 (retrain): **NONE_FAILED_MIN_ONE_SUCCESS** — runs even if predict was skipped
- Task 7 (promote): **NONE_FAILED_MIN_ONE_SUCCESS** — runs even if evaluate was skipped
- Task 8 (monitor): **ALL_DONE** — always runs, even on failure (observability)

## AWS Infrastructure

### Network (VPC)

```
VPC (10.0.0.0/16)
  |
  +-- Public Subnets (10.0.1.0/24, 10.0.2.0/24)
  |     +-- EC2 (Airflow) — internet-facing
  |
  +-- Private Subnets (10.0.3.0/24, 10.0.4.0/24)
        +-- RDS PostgreSQL (Airflow metadata)
        +-- ElastiCache Redis (Feast online store)
        +-- Lambda (inference, in VPC for Redis access)
        +-- S3 Gateway Endpoint (free, no NAT needed)
        +-- DynamoDB Gateway Endpoint (free)
```

### Compute Resources

| Resource | Type | Purpose | Subnet |
|----------|------|---------|--------|
| EC2 | t3.small (2 vCPU, 2GB + 4GB swap) | Airflow + all DAG tasks | Public |
| RDS | db.t3.micro (PostgreSQL 16) | Airflow metadata store | Private |
| ElastiCache | cache.t3.micro (Redis 7.1) | Feast online feature store | Private |
| Lambda (predictor) | 512MB, 60s timeout, x86_64 | ONNX inference via container image | Private |
| Lambda (backfill) | 256MB, 120s timeout | Backfill actuals to DynamoDB | Private |

### Storage

| Service | Purpose | Key Paths |
|---------|---------|-----------|
| S3 | Central data + model store | `raw/btc_ohlcv/`, `feast/offline/`, `models/`, `runs/` |
| DynamoDB | Prediction log with backfilled actuals | Table: `crypto-vol-predictions` |
| Redis | Real-time feature serving (75-min TTL) | Feast online store |

### Serving Path (Lambda)

```
User -> API Gateway (GET /predict) -> Lambda -> Redis (read features)
                                         |-> S3 (load ONNX model)
                                         |-> ONNX Runtime (inference)
                                         |-> DynamoDB (write prediction)
                                         |-> Response (prediction + confidence)
```

### Monitoring & Alerting

| Component | Purpose |
|-----------|---------|
| CloudWatch (5 metrics) | rolling_accuracy, drift_score, model_version, prediction_latency, retrain_count |
| SNS (drift-alerts) | Email notifications on drift detection |
| SNS (billing-alerts) | Cost threshold notifications |
| W&B | Experiment tracking, feature importance, model artifacts |
| EventBridge | Triggers backfill Lambda every 30 minutes |

### Security Groups

```
Airflow EC2 SG:  Inbound 22 (SSH), 8080 (UI)  |  Outbound: all
RDS SG:          Inbound 5432 from Airflow SG  |  Outbound: all
Redis SG:        Inbound 6379 from Airflow SG + Lambda SG
Lambda SG:       Outbound 443 (S3/APIs) + 6379 (Redis)
```

### IAM Roles

- **EC2 Role**: S3 (read/write), DynamoDB (read/write), CloudWatch (publish), Lambda (invoke/update), ECR (pull)
- **Lambda Role**: S3 (read), DynamoDB (write), VPC access, CloudWatch logs
- **EventBridge Role**: Lambda invoke (backfill only)
