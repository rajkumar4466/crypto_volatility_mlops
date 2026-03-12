# Crypto Volatility MLOps

## What This Is

An end-to-end MLOps learning project that predicts Bitcoin price volatility — whether the next 30 minutes will see a >2% price swing (VOLATILE) or stay calm (<2% swing). The ML model is intentionally simple (XGBoost, trains in <2 seconds); the real focus is the full MLOps infrastructure: automated retraining, drift detection, experiment tracking, orchestration, feature store, CI/CD, and monitoring. Designed so the entire retrain→evaluate→promote cycle can be observed multiple times in a single day.

## Core Value

A working, observable MLOps loop where data drift triggers automated retraining, model evaluation, and promotion — all visible through dashboards and alerts within hours, not weeks.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Ingest BTC 1-minute candle data from CoinGecko free API (no API key)
- [ ] Compute 12 engineered features (volatility, RSI, volume spike, moving averages, etc.)
- [ ] Label data: VOLATILE (>2% swing in next 30 min) vs CALM
- [ ] Train XGBoost classifier with GridSearchCV
- [ ] Export trained model to ONNX format
- [ ] Serve predictions via FastAPI + ONNX Runtime on AWS Lambda
- [ ] Expose prediction endpoint via API Gateway (GET /predict, GET /health)
- [ ] Feature store: Feast with S3 offline store + Redis (ElastiCache) online store
- [ ] Single source of truth for feature computation — no training-serving skew
- [ ] Experiment tracking: W&B (free tier) for dashboards + S3 JSON backup
- [ ] Model registry: S3 versioned objects (current.onnx, v{n}.onnx)
- [ ] Automated model promotion: new model replaces current only if metrics improve
- [ ] Orchestration: Apache Airflow DAG on EC2 with RDS PostgreSQL metadata store
- [ ] DAG: ingest → compute features → predict → retrain → evaluate → promote → monitor
- [ ] Scheduled retraining every 30 minutes + drift-triggered retraining
- [ ] Data drift detection: KS-test on feature distributions (scipy)
- [ ] Model drift detection: rolling accuracy on backfilled actuals
- [ ] Alerting: SNS → email on drift detection or accuracy drop
- [ ] CloudWatch dashboard: rolling accuracy, drift score, model version, latency
- [ ] CI/CD: GitHub Actions — lint + test on PR, build + deploy on merge
- [ ] Container images: Docker → ECR (single shared image for Lambda)
- [ ] Infrastructure as Code: Terraform for all AWS resources
- [ ] All AWS services within free tier ($0 cost)

### Out of Scope

- Profitable trading strategy — this is an MLOps learning project, not a trading bot
- Multi-coin support — BTC only, keeps it focused
- GPU inference — XGBoost + ONNX Runtime on CPU is sufficient
- Kubernetes / EKS — Lambda + EC2 is enough for this scale
- MLflow server — W&B + S3 covers experiment tracking without hosting a server
- Frontend dashboard — CloudWatch + W&B + Airflow UI are sufficient
- Real-time streaming (Kafka, Kinesis) — polling every 5 min is adequate

## Context

- **Data source**: CoinGecko free API provides BTC 1-minute OHLCV candles with no API key required
- **Drift characteristics**: Crypto markets shift regimes multiple times per day (calm → volatile → crash → recovery), making drift detection and retraining observable within hours
- **Training speed**: XGBoost on ~288 samples with 12 features trains in <2 seconds, making automated retraining feasible inside Lambda or Airflow tasks
- **Learning goal**: Build every MLOps layer from scratch to understand the patterns that transfer to production systems (Triton, Kubeflow, MLflow Registry, Feast at scale)
- **Existing projects**: This sits alongside other ML projects (fraud detection, housing price predictor, etc.) in the models/ directory but is fully independent

## Constraints

- **Cost**: $0 — all AWS services must stay within free tier (Lambda, S3, DynamoDB, EC2 t3.micro, RDS db.t3.micro, ElastiCache t3.micro, ECR, API Gateway, EventBridge, CloudWatch, SNS)
- **Free tier time limits**: EC2, RDS, and ElastiCache are free for 12 months only
- **No API keys for data**: CoinGecko free tier, no authentication
- **Ephemeral deployment**: Designed to spin up in the morning, observe cycles all day, tear down by evening (terraform destroy)
- **Single region**: us-east-1 for simplicity and free tier availability

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| XGBoost over RandomForest | Better accuracy on tabular data, fast training, easy ONNX export | — Pending |
| Airflow over Prefect/EventBridge | Full DAG dependency management, retries, UI — worth the EC2 cost (free tier) | — Pending |
| W&B over MLflow server | Free hosted dashboard, no server to maintain, 5 lines of code | — Pending |
| Feast over custom feature logic | Eliminates training-serving skew, S3+Redis backends fit free tier | — Pending |
| Lambda over ECS Fargate | Free tier, no always-on cost, cold start acceptable for 5-min intervals | — Pending |
| Volatility prediction over price direction | Actually solvable (70-80% accuracy), drift is dramatic and fast | — Pending |
| ONNX over raw joblib | Framework-agnostic, faster inference, smaller serving container | — Pending |

---
*Last updated: 2026-03-12 after initialization*
