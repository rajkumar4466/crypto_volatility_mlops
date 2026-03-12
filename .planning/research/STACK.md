# Stack Research

**Domain:** Crypto Volatility MLOps (end-to-end ML pipeline with full MLOps infrastructure)
**Researched:** 2026-03-12
**Confidence:** MEDIUM (versions verified via PyPI/official docs; some AWS free-tier constraints have changed as of July 2025)

---

## Recommended Stack

### ML Core

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| XGBoost | 3.2.0 | Binary classifier for volatility prediction | Best tabular accuracy among tree methods; trains on 288 samples in <2s on CPU; wide ONNX ecosystem support. Requires Python >=3.10. |
| scikit-learn | 1.8.0 | GridSearchCV hyperparameter tuning, preprocessing pipelines | Standard wrapper for XGBoost via sklearn API; GridSearchCV integrates naturally with XGBoost's sklearn interface. |
| pandas | 3.0.1 | Feature engineering, data manipulation | De-facto for OHLCV tabular data; requires Python >=3.11 (matches XGBoost 3.x requirement). |
| scipy | 1.17.1 | KS-test drift detection (`scipy.stats.ks_2samp`) | `ks_2samp` is the standard nonparametric test for detecting feature distribution shift; returns p-value directly usable as a threshold trigger. Requires Python >=3.11. |
| numpy | (scipy/pandas pin) | Numerical operations | Pulled transitively; no separate pin needed. |

### ONNX Export & Serving

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| onnxmltools | 1.16.0 | Convert trained XGBoost model to ONNX | The standard converter for XGBoost → ONNX. XGBoost 3.x does NOT have native ONNX export; `save_model()` only supports JSON/UBJSON formats. Use `onnxmltools.convert_xgboost()`. |
| skl2onnx | 1.20.0 | ONNX conversion for sklearn pipelines (required by onnxmltools) | onnxmltools delegates XGBoost conversion through skl2onnx's operator registry; must be installed alongside onnxmltools. |
| onnxruntime | 1.24.3 | CPU inference inside Lambda and Airflow tasks | ~13MB package size; fast CPU inference; sub-millisecond latency on XGBoost-scale models; officially supported in AWS Lambda containers. No GPU driver needed. |
| FastAPI | 0.135.1 | REST API wrapper for Lambda inference endpoint | Minimal overhead on top of ONNX Runtime; async support; clean OpenAPI docs; requires Python >=3.10. Deployed via Mangum adapter for Lambda. |
| Mangum | latest stable | ASGI-to-Lambda adapter for FastAPI | Translates API Gateway events to ASGI; required to run FastAPI inside Lambda. |

### Feature Store

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Feast | 0.61.0 | Feature store: offline (S3) + online (Redis/ElastiCache) | Eliminates training-serving skew — single feature definition used at train time (S3 Parquet) and serve time (Redis). S3 offline store and Redis online store both have free-tier equivalents. File-based registry on S3 sufficient for this scale. |

### Experiment Tracking

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| wandb | 0.25.1 | Experiment tracking, run dashboards, metric history | Free hosted dashboard (100GB storage, unlimited tracking hours on free tier); 5-line integration; no server to maintain unlike MLflow. Backup metrics to S3 JSON for redundancy. |

### Orchestration

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Apache Airflow | 3.1.8 | DAG orchestration: ingest → features → retrain → evaluate → promote | Full DAG dependency management with retries and a UI; supports both scheduled (cron) and event-triggered (drift) DAGs. Airflow 3.0 added improved Task SDK and asset-based scheduling relevant to ML pipelines. |

### Infrastructure & Deployment

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Terraform CLI | 1.14.7 | IaC for all AWS resources | Open-source, free; declarative AWS resource definitions; `terraform destroy` enables clean daily teardown. AWS provider is the most mature Terraform integration. |
| AWS Lambda | N/A (managed) | Serverless inference endpoint | 1M invocations/month + 400K GB-seconds always-free; cold start acceptable for 5-min polling intervals; 10GB container image limit covers ONNX Runtime + model. |
| AWS API Gateway | N/A (managed) | HTTP trigger for Lambda | 1M calls/month free tier; routes GET /predict and GET /health to Lambda. |
| AWS S3 | N/A (managed) | Model registry (current.onnx, v{n}.onnx), Feast offline store, W&B JSON backup | 5GB always-free; versioned objects serve as the model registry without a dedicated server. |
| AWS EC2 | t3.micro | Airflow scheduler + worker | Free-tier eligible (750 hrs/month, 12 months for accounts before July 2025). **CRITICAL: 1GB RAM is below Airflow's recommended 4GB.** Mitigation: configure 4GB swap + SequentialExecutor + external PostgreSQL on RDS. |
| AWS RDS PostgreSQL | db.t3.micro | Airflow metadata database | Free tier (750 hrs/month, 12 months); PostgreSQL 16+ required by Airflow 3.x; do NOT use SQLite in production Airflow. |
| AWS ElastiCache Redis | cache.t3.micro | Feast online store for sub-10ms feature retrieval | Free tier (750 hrs/month, 12 months for accounts before July 2025); Redis is Feast's preferred online store for real-time inference. |
| AWS ECR | N/A (managed) | Container registry for Lambda image | 500MB/month free; Lambda image pulled from ECR at deploy time. |
| AWS CloudWatch | N/A (managed) | Monitoring dashboards, alerting | 10 custom metrics free; dashboard for rolling accuracy, drift score, model version, latency. |
| AWS SNS | N/A (managed) | Email alerts on drift/accuracy drop | 1M notifications/month free; email endpoint costs nothing. |
| GitHub Actions | N/A (managed) | CI/CD: lint+test on PR, build+deploy on merge | 2000 minutes/month free for public repos; native Docker build + ECR push + Terraform apply. |
| Docker | latest stable | Container build for Lambda | Required for Lambda container images; local build context for ECR push. |

---

## Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| requests | latest | CoinGecko API HTTP calls | Ingestion task only; simple sync HTTP suffices for 5-min polling. |
| pyarrow | latest | Parquet read/write for Feast S3 offline store | Required by Feast S3 provider for offline materialization. |
| boto3 | latest | AWS SDK: S3 uploads, SNS publish, CloudWatch metrics | Used across all tasks that interact with AWS services. |
| uvicorn | latest | ASGI server (local testing of FastAPI) | Dev/test only; Lambda uses Mangum adapter not uvicorn directly. |
| pytest | latest | Unit tests for feature engineering, drift detection, model evaluation | CI gate on PR; covers feature computation purity and model promotion logic. |
| black + ruff | latest | Code formatting + linting | CI gate on PR; ruff replaces flake8+isort with single fast tool. |

---

## Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Terraform CLI 1.14.7 | Provision/destroy AWS resources | `terraform init`, `terraform apply`, `terraform destroy` for daily workflow. |
| AWS CLI v2 | Ad-hoc AWS operations, ECR login | Required for `aws ecr get-login-password` during Docker push. |
| Docker Desktop | Local container builds | Build Lambda image locally before pushing to ECR. |
| Python 3.11 | Runtime for all components | Minimum required by pandas 3.x, scipy 1.17.x, and Airflow 3.1.x. Use 3.11 for broadest compatibility across all packages. |

---

## Installation

```bash
# Python version
python --version  # Must be 3.11+

# ML core
pip install xgboost==3.2.0 scikit-learn==1.8.0 pandas==3.0.1 scipy==1.17.1

# ONNX pipeline
pip install onnxmltools==1.16.0 skl2onnx==1.20.0 onnxruntime==1.24.3

# Serving
pip install fastapi==0.135.1 mangum uvicorn

# Feature store
pip install feast==0.61.0 pyarrow

# Experiment tracking
pip install wandb==0.25.1

# Orchestration (on EC2, not locally)
pip install apache-airflow==3.1.8

# AWS + utilities
pip install boto3 requests

# Dev dependencies
pip install pytest black ruff
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| XGBoost 3.2.0 | LightGBM | LightGBM is equally fast and has better categorical support; choose it if you add categorical coin metadata. XGBoost wins here on ONNX export tooling maturity. |
| XGBoost 3.2.0 | sklearn RandomForest | Lower accuracy on tabular data; slower to train at scale; no meaningful advantage here. Avoid. |
| onnxmltools | skl2onnx alone | Use skl2onnx alone only if the model is wrapped in a full sklearn Pipeline; onnxmltools is needed for raw XGBClassifier objects. |
| onnxruntime | TensorFlow Serving / TorchServe | Massive overhead for a lightweight XGBoost model; CPU ONNX Runtime is the minimal viable serving solution. |
| FastAPI + Mangum | AWS SageMaker endpoints | SageMaker has no free tier; costs $0.10+/hr minimum. Lambda is the correct free-tier serving choice. |
| Feast | Custom feature computation | Custom code duplicated between training and serving creates training-serving skew — the most common MLOps bug. Feast is worth the setup complexity. |
| Feast | Tecton / Hopsworks | Paid/hosted; not compatible with $0 budget constraint. |
| wandb | MLflow (self-hosted) | MLflow requires hosting a tracking server (an EC2 instance or RDS), adding cost and complexity. W&B free tier eliminates this entirely. |
| Airflow 3.1.8 | Prefect | Prefect Cloud free tier is generous, but Prefect's DAG model (flows/tasks) has less mature dependency visualization than Airflow. Airflow 3.0's Task SDK improvements close previous DX gaps. |
| Airflow 3.1.8 | AWS EventBridge | EventBridge handles scheduling but has no DAG dependency management, retries with backoff, or task-level UI. Not a substitute for Airflow. |
| RDS PostgreSQL | SQLite for Airflow metadata | SQLite is explicitly unsupported for production Airflow (Airflow docs state "development only"); LocalExecutor with SQLite produces zombie task issues under concurrent load. |
| Terraform | AWS CDK / Pulumi | CDK/Pulumi require Node.js or Python SDK layers; Terraform HCL is simpler for infrastructure-only work and has broader free-tier community examples. |
| Lambda containers | Lambda ZIP packages | ZIP packages have a 250MB uncompressed limit; onnxruntime alone approaches this. Container images allow up to 10GB, making the ONNX + FastAPI stack viable. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| XGBoost `save_model()` for ONNX | `save_model()` only outputs JSON/UBJSON formats, not ONNX. There is no native ONNX export in XGBoost 3.x. | `onnxmltools.convert_xgboost()` |
| SQLite as Airflow metadata DB | Official Airflow docs classify SQLite as "development only." LocalExecutor + SQLite produces zombie tasks. | RDS PostgreSQL db.t3.micro |
| GPU-enabled onnxruntime | `onnxruntime-gpu` requires CUDA drivers; Lambda has no GPU. XGBoost inference at this model size is <5ms on CPU anyway. | `onnxruntime` (CPU-only build, ~13MB) |
| ElastiCache Serverless | Explicitly excluded from ElastiCache free tier; would incur charges immediately. | Provisioned `cache.t3.micro` node |
| SageMaker for serving | No free tier; minimum $0.10/hr endpoint cost. Breaks $0 budget constraint. | Lambda + API Gateway |
| Kafka / Kinesis for ingestion | Real-time streaming is overkill; Kinesis Data Streams has no free tier. 5-min CoinGecko polling achieves the same observable drift cycles. | CoinGecko REST API + scheduled Airflow task |
| Kubernetes / EKS | No free tier; EC2 + Lambda architecture is sufficient. Out of scope per PROJECT.md. | EC2 (Airflow) + Lambda (serving) |
| MLflow self-hosted | Requires additional EC2 instance or RDS; increases cost and operational burden. | W&B free tier + S3 JSON backup |
| t3.medium EC2 for Airflow | NOT free-tier eligible; only t3.micro qualifies for 750 hrs/month. | t3.micro with 4GB swap configured (see note below) |

---

## Stack Patterns by Variant

**For Airflow on t3.micro (free tier constraint):**
- Configure 4GB EBS-backed swap: `sudo fallocate -l 4G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`
- Use `SequentialExecutor` (not LocalExecutor) to minimize concurrent memory pressure
- Keep DAG task footprints small: spawn Python subprocesses rather than loading large objects in the scheduler
- External PostgreSQL on RDS db.t3.micro handles metadata; scheduler RAM is not consumed by DB
- Accept that with heavy concurrent tasks, the instance may OOM-kill; design tasks to be idempotent and retriable

**For ONNX export pipeline:**
- Train XGBoost with sklearn API (`XGBClassifier`) so onnxmltools can introspect the sklearn-compatible interface
- Define `initial_type` as `[('float_input', FloatTensorType([None, 12]))]` matching your 12-feature vector
- Validate the converted model with `onnxruntime.InferenceSession` before promoting

**For Lambda cold start mitigation:**
- Use provisioned concurrency only if cold starts become unacceptable; at 5-min polling intervals, cold start is acceptable
- Keep Lambda memory at 512MB minimum for ONNX Runtime initialization; tune up if needed within free tier GB-seconds budget

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| xgboost==3.2.0 | Python >=3.10 | Requires 3.10+; use Python 3.11 for all-package compatibility |
| pandas==3.0.1 | Python >=3.11 | Hard requirement: Python 3.11+ |
| scipy==1.17.1 | Python >=3.11 | Hard requirement: Python 3.11+ |
| scikit-learn==1.8.0 | Python >=3.11 | Hard requirement: Python 3.11+ |
| apache-airflow==3.1.8 | Python 3.10-3.13, PostgreSQL 13+ | SQLite dev-only; requires RDS |
| feast==0.61.0 | Python 3.9+ | No conflict with 3.11 |
| onnxmltools==1.16.0 | skl2onnx>=1.14, Python 3.9+ | Must install skl2onnx alongside |
| onnxruntime==1.24.3 | Python 3.9+ | CPU-only; arm64 Lambda has known issues with older onnxruntime (pre-1.12); use x86_64 Lambda to avoid the ARM64 `Illegal instruction` bug |

**Python version decision: Use 3.11.** It satisfies the hard lower bound from pandas/scipy/sklearn/Airflow while avoiding potential incompatibilities at the leading edge (3.12/3.13) where fewer Airflow provider packages have been tested.

---

## AWS Free Tier Constraints (Critical)

All free-tier time-limited resources expire 12 months after account creation (for accounts created before July 15, 2025):

| Service | Free Tier Limit | Notes |
|---------|----------------|-------|
| EC2 t3.micro | 750 hrs/month, 12 months | Sufficient for daily spin-up/tear-down |
| RDS db.t3.micro | 750 hrs/month, 12 months | Use `terraform destroy` after each session |
| ElastiCache cache.t3.micro | 750 hrs/month, 12 months | Provisioned only; Serverless is NOT free |
| Lambda | 1M invocations + 400K GB-sec/month, always-free | Never expires |
| S3 | 5GB storage, always-free | Never expires |
| API Gateway | 1M calls/month, 12 months | Sufficient for low-volume predictions |
| CloudWatch | 10 custom metrics, always-free | Sufficient for this project |
| SNS | 1M notifications/month, always-free | Never expires |

**Deploy pattern:** `terraform apply` in the morning → observe MLOps cycles → `terraform destroy` in the evening. This keeps EC2, RDS, and ElastiCache hours well under 750/month even if run daily.

---

## Sources

- PyPI — xgboost 3.2.0: https://pypi.org/project/xgboost/ (verified 2026-03-12) — HIGH confidence
- PyPI — onnxruntime 1.24.3: https://pypi.org/project/onnxruntime/ (verified 2026-03-12) — HIGH confidence
- PyPI — onnxmltools 1.16.0: https://pypi.org/project/onnxmltools/ (verified 2026-03-12) — HIGH confidence
- PyPI — skl2onnx 1.20.0: https://onnx.ai/sklearn-onnx/ (verified 2026-03-12) — HIGH confidence
- PyPI — fastapi 0.135.1: https://pypi.org/project/fastapi/ (verified 2026-03-12) — HIGH confidence
- PyPI — feast 0.61.0: https://pypi.org/project/feast/ (verified 2026-03-12) — HIGH confidence
- PyPI — wandb 0.25.1: https://pypi.org/project/wandb/ (verified 2026-03-12) — HIGH confidence
- PyPI — apache-airflow 3.1.8: https://pypi.org/project/apache-airflow/ (verified 2026-03-12) — HIGH confidence
- PyPI — pandas 3.0.1: https://pypi.org/project/pandas/ (verified 2026-03-12) — HIGH confidence
- PyPI — scipy 1.17.1: https://pypi.org/project/scipy/ (verified 2026-03-12) — HIGH confidence
- PyPI — scikit-learn 1.8.0: https://pypi.org/project/scikit-learn/ (verified 2026-03-12) — HIGH confidence
- Terraform install page — v1.14.7: https://developer.hashicorp.com/terraform/install (verified 2026-03-12) — HIGH confidence
- Airflow prerequisites (4GB RAM rec): https://airflow.apache.org/docs/apache-airflow/stable/installation/prerequisites.html — HIGH confidence
- XGBoost save_model docs (no ONNX): https://xgboost.readthedocs.io/en/stable/python/python_api.html — HIGH confidence
- AWS Lambda limits: https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html — HIGH confidence (10GB container, 1M invocations free)
- AWS EC2 free tier (t3.micro only): https://aws.amazon.com/ec2/faqs/ + https://aws.amazon.com/free/free-tier-faqs/ — HIGH confidence
- ElastiCache free tier: https://aws.amazon.com/elasticache/pricing/ (cache.t3.micro 750 hrs, Serverless excluded) — HIGH confidence
- W&B free tier: https://wandb.ai/site/pricing/ (100GB storage, unlimited hours) — MEDIUM confidence (marketing page, not product changelog)
- CoinGecko Demo API: https://docs.coingecko.com/docs/common-errors-rate-limit (30 calls/min, 10K/month) — MEDIUM confidence
- Feast AWS docs: https://docs.feast.dev/reference/providers/amazon-web-services — MEDIUM confidence (version not pinned in docs)
- ARM64 ONNX Runtime Lambda bug: https://github.com/microsoft/onnxruntime/issues/10038 — MEDIUM confidence (historical issue; verify status at deploy time)

---

*Stack research for: Crypto Volatility MLOps*
*Researched: 2026-03-12*
