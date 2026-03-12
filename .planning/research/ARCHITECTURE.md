# Architecture Research

**Domain:** Crypto Volatility MLOps — end-to-end ML pipeline with feature store, orchestration, serving, and monitoring
**Researched:** 2026-03-12
**Confidence:** MEDIUM (architecture patterns are well-established; specific free-tier AWS constraint combinations are LOW confidence in some places)

## Standard Architecture

### System Overview

The system follows the FTI (Feature / Training / Inference) pipeline decomposition pattern, which is the current industry standard for MLOps architectures. Three independently deployable pipelines share a feature store as the single source of truth.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATION LAYER                              │
│   Airflow DAG on EC2 (schedules + triggers all pipeline stages)         │
└─────────┬──────────────────────┬──────────────────────┬─────────────────┘
          │                      │                      │
          v                      v                      v
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────────┐
│  FEATURE PIPELINE │  │ TRAINING PIPELINE │  │     INFERENCE PIPELINE       │
│                  │  │                  │  │                              │
│ CoinGecko API    │  │ XGBoost GridCV   │  │ API Gateway → Lambda         │
│ → Raw OHLCV      │  │ → ONNX export    │  │ → Feast online lookup        │
│ → 12 features    │  │ → W&B tracking   │  │ → ONNX Runtime               │
│ → Feast offline  │  │ → S3 registry    │  │ → prediction response        │
│   (S3 Parquet)   │  │ → promote gate   │  │                              │
└────────┬─────────┘  └────────┬─────────┘  └──────────────────────────────┘
         │                     │
         v                     v
┌─────────────────────────────────────────────────────────────────────────┐
│                         FEAST FEATURE STORE                              │
│  Registry (S3 JSON)  │  Offline Store (S3 Parquet)  │  Online (Redis)   │
│  Feature definitions │  Historical features for     │  Latest features  │
│  Entity definitions  │  point-in-time training      │  for <10ms serve  │
└─────────────────────────────────────────────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────────────────────────────────────┐
│                     MONITORING & ALERTING LAYER                          │
│  Drift detector (KS-test) → SNS → email alert → Airflow drift DAG      │
│  CloudWatch dashboard: accuracy, drift score, version, latency          │
│  W&B: experiment history, metric trends, model comparison               │
└─────────────────────────────────────────────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────────────────────────────────────┐
│                      CI/CD & INFRASTRUCTURE LAYER                        │
│  GitHub Actions: lint/test on PR, build+push ECR image on merge        │
│  Terraform: provisions EC2, RDS, ElastiCache, Lambda, S3, SNS, CW      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| CoinGecko Ingestor | Polls BTC 1-min OHLCV, writes raw candles | Feast offline store (S3), Airflow (triggered by) |
| Feature Engineering | Computes 12 features (RSI, vol, MAs, etc.), labels rows | Feast (writes feature rows), Airflow (triggered by) |
| Feast Offline Store | S3 Parquet — historical feature data with point-in-time join | Training pipeline (reads), Feature engineering (writes) |
| Feast Online Store | Redis — latest feature values, <10ms latency | Inference Lambda (reads), Materialization job (writes) |
| Feast Registry | S3 JSON — entity/feature view definitions | All Feast clients (reads), Feature engineering (writes) |
| XGBoost Trainer | Loads historical features from Feast, trains GridSearchCV, exports ONNX | Feast offline, W&B, S3 model registry, Airflow |
| W&B Tracker | Logs runs, metrics, hyperparams, model artifacts | Training pipeline (writes), CloudWatch (metric sync optional) |
| S3 Model Registry | Versioned ONNX files: `current.onnx`, `v{n}.onnx` | Training pipeline (writes), Lambda (reads at cold start) |
| Promotion Gate | Compares new model metrics vs current; promotes only on improvement | Training pipeline, S3 registry, W&B |
| Lambda + ONNX Runtime | Loads `current.onnx` from S3 on cold start, serves predictions | API Gateway (triggered by), Feast online (reads features), CloudWatch (metrics) |
| API Gateway | Routes GET /predict and GET /health to Lambda | External callers, Lambda |
| Drift Detector | KS-test on feature distributions, rolling accuracy check | Feast offline (reads recent data), SNS (publishes alerts), Airflow (triggers retraining) |
| SNS | Publishes alerts on drift or accuracy drop | Drift detector (writes), Email/phone (delivers) |
| CloudWatch | Dashboard for accuracy, drift score, model version, latency | Lambda (metrics source), Airflow tasks (metrics source) |
| Airflow DAG | Master orchestrator — sequences all tasks, handles retries, triggers | All pipeline components |
| RDS PostgreSQL | Airflow metadata store (DAG state, task logs) | Airflow only |
| EC2 t3.micro | Hosts Airflow scheduler + webserver | RDS, all downstream AWS services |
| GitHub Actions | CI: lint/test; CD: Docker build, ECR push, Terraform apply | ECR, Terraform, Lambda |
| Terraform | Provisions all AWS resources declaratively | AWS APIs |

## Recommended Project Structure

```
crypto_volatility_mlops/
├── src/
│   ├── ingestion/          # CoinGecko API client, raw OHLCV writer
│   │   └── coingecko.py
│   ├── features/           # Feature computation, labeling, Feast write
│   │   ├── compute.py      # 12 feature functions (RSI, vol, MAs, etc.)
│   │   ├── labels.py       # VOLATILE/CALM labeling logic
│   │   └── store.py        # Feast write to offline + materialize to online
│   ├── training/           # XGBoost train, ONNX export, W&B logging
│   │   ├── train.py        # GridSearchCV + train loop
│   │   ├── export.py       # skl2onnx or xgboost native ONNX export
│   │   └── promote.py      # promotion gate: compare metrics, swap current.onnx
│   ├── serving/            # Lambda handler + FastAPI app
│   │   ├── handler.py      # Lambda entrypoint
│   │   ├── app.py          # FastAPI routes (/predict, /health)
│   │   └── inference.py    # Load model from S3, run ONNX Runtime session
│   ├── monitoring/         # Drift detection + CloudWatch + SNS
│   │   ├── drift.py        # KS-test on feature distributions
│   │   ├── accuracy.py     # Rolling accuracy on backfilled actuals
│   │   └── alerts.py       # SNS publish helpers
│   └── utils/              # Shared config, logging, AWS clients
│       ├── config.py
│       └── aws.py
├── dags/                   # Airflow DAG definitions
│   └── volatility_dag.py   # Single DAG: ingest→features→predict→train→eval→promote→monitor
├── feast/                  # Feast feature store definitions
│   ├── feature_store.yaml  # Registry + offline + online config
│   └── features.py         # FeatureView, Entity, Feature definitions
├── terraform/              # IaC for all AWS resources
│   ├── main.tf
│   ├── lambda.tf
│   ├── ec2_airflow.tf
│   ├── rds.tf
│   ├── elasticache.tf
│   ├── s3.tf
│   ├── api_gateway.tf
│   ├── sns_cloudwatch.tf
│   └── variables.tf
├── tests/                  # Unit + integration tests
│   ├── test_features.py    # Feature computation correctness
│   ├── test_training.py    # Model trains, ONNX exports cleanly
│   └── test_serving.py     # Lambda handler returns correct shape
├── .github/workflows/      # GitHub Actions CI/CD
│   ├── ci.yml              # lint + test on PR
│   └── cd.yml              # build ECR image + terraform apply on merge to main
├── Dockerfile              # Single image for Lambda serving
└── requirements.txt
```

### Structure Rationale

- **src/ split by pipeline stage:** Mirrors the FTI decomposition — each subdirectory can be understood and tested independently. Serving code never imports training code.
- **dags/ at root:** Airflow expects DAGs in a specific folder; keeping it separate from src/ avoids circular imports and clarifies Airflow's role as an orchestrator, not a library.
- **feast/ at root:** Feast CLI expects `feature_store.yaml` at a fixed path. Co-locating feature definitions with the config prevents registry drift.
- **terraform/ at root:** Infrastructure-as-code is a first-class concern. Not buried in a deploy/ folder where it gets forgotten.
- **Single Dockerfile:** One shared Lambda image avoids dependency skew between serving and CI environments. Lambda container images can be up to 10GB, so including all Python deps is fine.

## Architectural Patterns

### Pattern 1: FTI Pipeline Decomposition (Feature / Training / Inference)

**What:** Decompose the ML system into three independently operable pipelines that share the feature store as their only coupling point. Feature pipeline writes to Feast offline. Training pipeline reads from Feast offline. Inference pipeline reads from Feast online. No pipeline imports the other's code.

**When to use:** Always for this project. Prevents training-serving skew by making feature definitions the single source of truth. Enables each pipeline to be retried, scaled, or replaced independently.

**Trade-offs:** Adds operational complexity (three pipelines to monitor vs one script). Worth it because training-serving skew is the most common silent failure mode in production ML (affects ~40% of deployed models per recent surveys).

**Example:**
```python
# features/store.py — the only place features are defined
FEATURE_VIEW = FeatureView(
    name="btc_volatility_features",
    entities=["btc"],
    schema=[
        Field(name="rsi_14", dtype=Float32),
        Field(name="vol_30m", dtype=Float32),
        # ... 10 more features
    ],
    source=FileSource(path="s3://bucket/features/", ...),
    ttl=timedelta(hours=2),
)

# training/train.py — reads from Feast, never recomputes features
training_df = store.get_historical_features(
    entity_df=entity_df,
    features=["btc_volatility_features:rsi_14", ...]
).to_df()

# serving/inference.py — reads from Feast online, same definitions
features = store.get_online_features(
    features=["btc_volatility_features:rsi_14", ...],
    entity_rows=[{"btc": "BTCUSDT"}]
).to_dict()
```

### Pattern 2: Promotion Gate with Metric Comparison

**What:** After each training run, compare the new model's held-out metrics against the currently deployed model before writing `current.onnx`. Promotion only happens if new_accuracy > current_accuracy (or other threshold). This prevents drift-triggered retraining from degrading model quality.

**When to use:** Every automated retraining cycle. Never blindly overwrite the current model.

**Trade-offs:** Requires storing current model metrics alongside the model artifact. Adds ~5 lines of code to the training pipeline. Essential for preventing automated retraining from causing production regressions.

**Example:**
```python
# training/promote.py
def promote_if_better(new_metrics: dict, s3_client, bucket: str):
    try:
        current = json.loads(s3_client.get_object(
            Bucket=bucket, Key="models/current_metrics.json"
        )["Body"].read())
        if new_metrics["accuracy"] <= current["accuracy"]:
            return False  # keep existing model
    except s3_client.exceptions.NoSuchKey:
        pass  # no current model — always promote first model

    s3_client.copy_object(
        Bucket=bucket,
        CopySource={"Bucket": bucket, "Key": f"models/v{new_metrics['version']}.onnx"},
        Key="models/current.onnx"
    )
    s3_client.put_object(
        Bucket=bucket, Key="models/current_metrics.json",
        Body=json.dumps(new_metrics)
    )
    return True
```

### Pattern 3: Cold-Start Model Loading in Lambda

**What:** Lambda loads `current.onnx` from S3 during the initialization phase (outside the handler function), caching the ONNX Runtime session in the execution environment. Subsequent invocations within the same container reuse the cached session.

**When to use:** Required for Lambda serving. Without this, every invocation fetches from S3 (~200ms overhead) instead of only cold starts (~500ms once per container lifecycle).

**Trade-offs:** After model promotion, Lambda containers continue using the old model until they recycle (minutes to hours). Mitigate by adding a `version` header check in the handler that forces a reload if S3 version differs from cached version. For a 5-minute polling interval, this staleness is acceptable.

**Example:**
```python
# serving/handler.py
import boto3
import onnxruntime as rt

# Runs once per cold start, cached for lifetime of container
s3 = boto3.client("s3")
model_bytes = s3.get_object(Bucket=BUCKET, Key="models/current.onnx")["Body"].read()
session = rt.InferenceSession(model_bytes)  # cached InferenceSession

def handler(event, context):
    features = get_online_features()  # Feast Redis lookup
    inputs = {session.get_inputs()[0].name: np.array([features], dtype=np.float32)}
    prediction = session.run(None, inputs)[0]
    return {"statusCode": 200, "body": json.dumps({"label": int(prediction[0])})}
```

## Data Flow

### Scheduled Retraining Flow (every 30 minutes)

```
Airflow Scheduler (cron: */30 * * * *)
    |
    v
Task 1: ingest_task
    CoinGecko API (GET /coins/bitcoin/ohlcv)
    --> raw OHLCV rows --> S3 raw store
    |
    v
Task 2: feature_task
    compute 12 features + VOLATILE/CALM labels
    --> feast.write_to_offline_store() --> S3 Parquet
    --> feast.materialize_incremental() --> Redis (ElastiCache)
    |
    v
Task 3: retrain_task
    feast.get_historical_features() (point-in-time join, last N rows)
    --> XGBoost GridSearchCV.fit()
    --> skl2onnx export --> S3 as v{n}.onnx
    --> wandb.log(metrics)
    |
    v
Task 4: evaluate_task
    load v{n}.onnx, run on hold-out set
    --> compare metrics vs current_metrics.json in S3
    --> if better: promote, write current.onnx + current_metrics.json
    --> else: skip promotion, log to W&B
    |
    v
Task 5: monitor_task
    KS-test on recent 30-min features vs training baseline
    rolling accuracy check on backfilled actuals
    --> if drift_score > threshold: SNS.publish(alert)
    --> CloudWatch.put_metric_data(accuracy, drift_score, model_version)
```

### Drift-Triggered Retraining Flow

```
monitor_task detects drift (KS p-value < 0.05)
    |
    --> SNS alert --> email notification
    |
    --> Airflow: trigger_dag("retrain_dag") immediately
    |
    [same flow as scheduled retraining above]
```

### Prediction Request Flow

```
Client
    |
    v
API Gateway (GET /predict?entity=BTCUSDT)
    |
    v
Lambda (cold start: load current.onnx from S3)
    |
    v
Feast online store (Redis ElastiCache)
    <-- get_online_features(entity_rows=[{"btc": "BTCUSDT"}])
    |
    v
ONNX Runtime InferenceSession.run()
    |
    v
CloudWatch: put_metric_data(latency, prediction_label)
    |
    v
API Gateway response {"label": "VOLATILE", "confidence": 0.82}
```

### Key Data Flows

1. **Feast materialization:** Offline S3 Parquet → `feast materialize_incremental` → Redis online store. Runs after every feature computation task. This is the only path from batch computation to real-time serving.
2. **Model promotion:** S3 `v{n}.onnx` → copy to `current.onnx` + update `current_metrics.json`. Lambda containers pick up the new model on their next cold start.
3. **Drift signal:** Monitoring task reads recent feature distributions from Feast offline, computes KS statistic, publishes to SNS + CloudWatch. If above threshold, triggers Airflow DAG via the Airflow REST API.

## Anti-Patterns

### Anti-Pattern 1: Duplicate Feature Logic in Training and Serving

**What people do:** Write a `compute_features()` function in the training notebook, then rewrite similar (but subtly different) logic in the Lambda handler for real-time computation.

**Why it's wrong:** Training-serving skew. If the training code computes RSI over a 14-period window and the serving code uses 12 periods (or a different data alignment), predictions in production will be systematically wrong. This affects ~40% of deployed models per industry surveys and is invisible until accuracy degrades unexpectedly.

**Do this instead:** Define all features once in `feast/features.py`. The feature pipeline writes to Feast. Training reads from Feast offline. Serving reads from Feast online. No feature math lives in the Lambda handler.

### Anti-Pattern 2: Blindly Overwriting current.onnx on Every Retraining Cycle

**What people do:** End the training task with `s3.copy_object(..., Key="current.onnx")` unconditionally.

**Why it's wrong:** Drift-triggered retraining fires precisely when data distribution is shifting. The new model trained on a short window of shifted data may perform worse than the baseline. Without a promotion gate, every retraining cycle risks degrading production accuracy.

**Do this instead:** Always compare new model metrics against stored current metrics before promoting. Promote only on improvement. Log both models to W&B for every run regardless of promotion outcome.

### Anti-Pattern 3: Loading the Model Inside the Lambda Handler Function

**What people do:** Put `model = onnxruntime.InferenceSession(...)` inside the `def handler(event, context)` body.

**Why it's wrong:** This runs on every single Lambda invocation, downloading the ONNX file from S3 and re-parsing it each time. At 5-minute prediction intervals this adds 200-500ms to every request and creates unnecessary S3 API calls.

**Do this instead:** Load the model at module level (outside the handler). Lambda execution environments reuse the module between warm invocations, so the session is loaded once per container lifetime (~minutes to hours).

### Anti-Pattern 4: Running Airflow Without a Persistent Metadata Store

**What people do:** Use Airflow's default SQLite metadata store (bundled in SequentialExecutor mode) to avoid provisioning RDS.

**Why it's wrong:** SQLite doesn't support concurrent task execution. With a multi-task DAG, tasks queue up sequentially and the 30-minute retraining window becomes unworkable. Also, SQLite on an EC2 instance has no durability — a restart loses all DAG history.

**Do this instead:** Use RDS PostgreSQL (db.t3.micro is free tier). Airflow's LocalExecutor with PostgreSQL supports parallel tasks and survives EC2 restarts. This is why the project spec includes RDS.

### Anti-Pattern 5: Deploying Infrastructure Manually Before Writing Terraform

**What people do:** Click through the AWS console to create the Lambda function, then write Terraform to "catch up" with reality.

**Why it's wrong:** Console-created resources accumulate undocumented settings (IAM policies, VPC subnet choices, environment variable values) that are hard to replicate. Terraform state becomes out of sync and `terraform destroy` fails to tear down manually created resources. Since this project is designed to be torn down daily, this is a critical failure mode.

**Do this instead:** Write Terraform first. Apply Terraform to create every resource. If something needs to change, change the Terraform and re-apply. The ephemeral teardown requirement makes IaC non-optional here.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| CoinGecko Free API | HTTP polling, no API key, GET `/coins/bitcoin/market_chart` | Rate limit: ~30 req/min on free tier. Poll every 5 min, fetch last 30 candles. No auth header needed. |
| W&B (Weights & Biases) | `wandb.init()` + `wandb.log()` in training task | Requires `WANDB_API_KEY` env var in Airflow/Lambda. Free tier: unlimited runs, 100GB storage. |
| GitHub Actions → ECR | `aws-actions/amazon-ecr-login` + `docker push` | Requires IAM role with ECR push permissions configured as GitHub OIDC trust. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Feature pipeline → Feast offline | `feast.write_to_offline_store()` Python SDK | Feature view must be registered in registry before writing |
| Feast offline → Training pipeline | `store.get_historical_features()` with entity_df | Entity DataFrame must include `event_timestamp` column for point-in-time join |
| Feast offline → Feast online | `feast materialize_incremental` CLI or Python | Copies latest feature values from S3 Parquet to Redis |
| Lambda → Feast online (Redis) | `store.get_online_features()` Python SDK | ElastiCache must be in same VPC as Lambda; requires VPC config on Lambda |
| Drift detector → Airflow | Airflow REST API POST `/dags/{dag_id}/dagRuns` | Airflow webserver must expose REST API (enabled by default in Airflow 2.x) |
| Training pipeline → S3 registry | `boto3.upload_file()` | Use versioned S3 bucket to prevent accidental overwrites |
| Lambda → CloudWatch | `boto3` `put_metric_data()` or Lambda automatic logging | Lambda automatically sends logs to CloudWatch Logs; custom metrics need explicit SDK calls |

## Build Order (Dependency Graph)

This is the order in which components must be built, driven by hard dependencies:

```
Phase 1: Foundation
  Terraform IaC (provisions all AWS resources)
  └── must exist before anything else runs in AWS

Phase 2: Data Infrastructure
  CoinGecko ingestion (standalone, no dependencies)
  └── Feast feature store definitions
      └── must exist before any feature writes or reads

Phase 3: Feature Pipeline
  Feature computation + labeling
  └── Feast offline writes (depends on: ingestion + Feast definitions)
  └── Feast materialization to Redis (depends on: offline store populated)

Phase 4: Training Pipeline
  XGBoost training (depends on: Feast offline with data)
  └── ONNX export (depends on: trained model)
  └── W&B tracking (depends on: training runs exist)
  └── S3 model registry (depends on: ONNX file)
  └── Promotion gate (depends on: S3 registry)

Phase 5: Serving
  Lambda + FastAPI handler (depends on: S3 model registry + Redis online store)
  └── API Gateway (depends on: Lambda deployed)

Phase 6: Orchestration
  Airflow DAG (wraps all above tasks; depends on: all pipeline components exist)
  └── RDS PostgreSQL must exist before Airflow starts

Phase 7: Monitoring & Alerting
  Drift detection (depends on: feature data in Feast offline + serving running)
  └── SNS alerts (depends on: drift detector)
  └── CloudWatch dashboard (depends on: Lambda metrics flowing)

Phase 8: CI/CD
  GitHub Actions (depends on: Docker image + Terraform + all components working)
```

**Critical path:** Terraform → Feast definitions → Feature pipeline → Training pipeline → Lambda serving → Airflow DAG → Monitoring.

Do not start the Airflow DAG before all individual pipeline components are verified working in isolation. Debugging a broken DAG with five failing tasks simultaneously is much harder than debugging each task as a standalone script first.

## Scaling Considerations

This project is explicitly designed for single-user, ephemeral operation on AWS free tier. Scale considerations are included to illustrate the architecture's evolution path, not as current requirements.

| Concern | Current (free tier, 1 user) | At 100 concurrent predictions | At production scale |
|---------|-----------------------------|-----------------------------|---------------------|
| Inference | Lambda cold start ~500ms acceptable | Provision concurrency to eliminate cold starts | Consider ECS Fargate or SageMaker endpoints |
| Feature store | Redis t3.micro, Feast Python SDK | Redis cluster mode, read replicas | Tecton or Hopsworks for sub-millisecond serving |
| Training | EC2 t3.micro, 2-second XGBoost | Larger instance, batch training on Fargate | SageMaker Training Jobs with spot instances |
| Orchestration | Airflow on single EC2 + LocalExecutor | Airflow with CeleryExecutor + multiple workers | MWAA (managed Airflow) or Kubeflow Pipelines |
| Data ingestion | CoinGecko polling every 5 min | WebSocket streaming, Kinesis ingestion | Kafka + Flink for real-time feature computation |

**First bottleneck on scale-up:** Lambda cold starts on concurrent requests. Fix: reserved concurrency + provisioned concurrency on Lambda before touching any other component.

## Sources

- [Hopsworks FTI Pipeline Architecture](https://www.hopsworks.ai/post/mlops-to-ml-systems-with-fti-pipelines) — MEDIUM confidence (authoritative on FTI pattern, not AWS-specific)
- [Feast Official Docs](https://docs.feast.dev) — HIGH confidence (official documentation)
- [Redis + Feast Feature Store Architecture](https://redis.io/blog/building-feature-stores-with-redis-introduction-to-feast-with-redis/) — MEDIUM confidence (vendor blog, verified against Feast docs)
- [AWS Feast + ElastiCache Pattern](https://aws.amazon.com/blogs/database/build-an-ultra-low-latency-online-feature-store-for-real-time-inferencing-using-amazon-elasticache-for-redis/) — MEDIUM confidence (AWS official blog)
- [Feast Practical Operation Guide 2026](https://www.youngju.dev/blog/ai-platform/2026-03-07-ai-platform-feast-feature-store-real-time-serving.en) — MEDIUM confidence (recent, March 2026)
- [ONNX + Lambda + FastAPI Pattern](https://pyimagesearch.com/2025/11/17/fastapi-docker-deployment-preparing-onnx-ai-models-for-aws-lambda/) — MEDIUM confidence (2025, verified pattern)
- [Airflow MLOps Best Practices](https://www.astronomer.io/docs/learn/airflow-mlops) — HIGH confidence (Astronomer official docs)
- [Solving Training-Serving Skew with Feast](https://medium.com/@scoopnisker/solving-the-training-serving-skew-problem-with-feast-feature-store-3719b47e23a2) — LOW confidence (Medium post, Nov 2025, unverified)
- [AWS MLOps Drift Detection + CloudWatch + SNS](https://aws.amazon.com/blogs/machine-learning/automate-model-retraining-with-amazon-sagemaker-pipelines-when-drift-is-detected/) — MEDIUM confidence (AWS official blog, SageMaker-specific but pattern applies)
- [MLOps on AWS Practical Guide](https://medium.com/platform-engineer/mlops-on-aws-a-practical-architecture-best-practices-guide-ff1d003cd4a5) — LOW confidence (Medium post, unverified author)

---
*Architecture research for: Crypto Volatility MLOps — end-to-end FTI pipeline on AWS free tier*
*Researched: 2026-03-12*
