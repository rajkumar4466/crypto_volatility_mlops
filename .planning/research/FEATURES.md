# Feature Research

**Domain:** Crypto Volatility MLOps — End-to-End Learning Project
**Researched:** 2026-03-12
**Confidence:** MEDIUM (MLOps lifecycle components are well-documented; crypto-specific MLOps integration is sparser in literature, verified via cross-source agreement)

---

## Feature Landscape

### Table Stakes (Users Expect These)

These are the features that make the MLOps lifecycle claim credible. If any of these are absent, the project does not demonstrate a real MLOps loop — it's just a notebook with a deploy script.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Automated data ingestion from live source | No MLOps without a live data feed; static datasets don't demonstrate the pipeline | LOW | CoinGecko free-tier 1-min OHLCV candles, no API key; polling every 5 min is adequate |
| Feature engineering pipeline (12 features) | Volatility window, RSI, volume spike, MAs are standard inputs for volatility classifiers; documented in literature | MEDIUM | Must compute at both training time (offline) and serving time (online) — single-source required |
| Feature store with online/offline split | Prevents training-serving skew — the #1 failure mode in production ML; Feast with S3 + Redis is the documented pattern | HIGH | Offline: S3 Parquet; Online: ElastiCache Redis; skew prevention is the learning outcome |
| Binary classification labeling | VOLATILE (>2% swing in 30 min) vs CALM is a well-posed classification problem; labeling logic must be deterministic and reproducible | LOW | Label computed from future 30-min window; must not leak future data at serving time |
| Model training with hyperparameter search | GridSearchCV over XGBoost hyperparams; demonstrates that training is not just a one-shot script | MEDIUM | Trains in <2 sec on ~288 samples with 12 features — fast enough for Airflow task |
| ONNX export for framework-agnostic serving | ONNX is the standard for production model interchange; skipping it means serving raw joblib, which is framework-coupled | LOW | XGBoost → ONNX → ONNX Runtime; onnxmltools handles conversion |
| Model serving via REST API | Required to demonstrate serving; Lambda + FastAPI + ONNX Runtime is the right pattern for this scale | MEDIUM | GET /predict, GET /health; API Gateway in front of Lambda |
| Experiment tracking with logged metrics | Without tracked experiments, there is no basis for model promotion decisions; W&B free tier is sufficient | LOW | Log: accuracy, AUC, precision/recall, hyperparams, feature importances per run |
| Model registry with versioned artifacts | Must version models to enable promotion and rollback; S3 versioned objects (current.onnx, v{n}.onnx) is the minimum viable pattern | LOW | No need for a hosted MLflow server; S3 + W&B artifacts covers this |
| Automated model promotion gate | New model only replaces current if metrics improve; this is the "Continuous Training" component of CT/CI/CD | MEDIUM | Compare challenger vs champion on held-out eval set; promote on improvement threshold |
| Pipeline orchestration with DAG | A single cron job is not MLOps; DAG with dependencies, retries, and observable task states is required | HIGH | Airflow on EC2 t3.micro; DAG: ingest → features → predict → retrain → evaluate → promote → monitor |
| Data drift detection | Drift detection is what triggers retraining; without it, retraining is just a cron job | MEDIUM | KS-test on feature distributions (scipy); crypto markets shift regimes multiple times per day |
| Model performance monitoring | Rolling accuracy on backfilled actuals proves the model is working (or failing); required to demonstrate monitoring loop | MEDIUM | Compute accuracy on predictions once actuals are known (30 min lag) |
| Alerting on drift or accuracy drop | Monitoring without alerting is just logging; SNS → email closes the loop | LOW | SNS topic; trigger from Airflow on drift score threshold or accuracy drop |
| CI/CD pipeline for code changes | Without CI/CD, the "Ops" in MLOps is absent; lint + test on PR, build + deploy on merge | MEDIUM | GitHub Actions; Docker → ECR → Lambda update |
| Infrastructure as Code | Terraform for all AWS resources; without IaC, the project cannot be reproduced or torn down cleanly | HIGH | Ephemeral by design: spin up, observe cycles, terraform destroy |
| Observability dashboard | Must be able to see the loop working; CloudWatch dashboard is the minimum viable monitoring surface | LOW | Metrics: rolling accuracy, drift score, model version in use, Lambda latency |

### Differentiators (Competitive Advantage)

These features go beyond a typical MLOps demo. They signal understanding of production nuances, not just infrastructure assembly.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Drift-triggered retraining (not just scheduled) | Most demos only show scheduled retraining; drift-triggered retraining demonstrates event-driven CT and is the production pattern | MEDIUM | KS-test in Airflow task; if drift score exceeds threshold, DAG branches to retrain immediately rather than waiting for schedule |
| Training-serving skew prevention via single feature definition | Few demo projects actually enforce this; Feast's registry enforces a single transformation definition used at both train and serve time | HIGH | The learning outcome: write the feature transform once, Feast applies it offline (S3) and online (Redis) identically |
| Automated rollback on degraded performance | If promoted model causes accuracy drop below baseline, auto-rollback to previous version; demonstrates production safety thinking | MEDIUM | Compare rolling accuracy of new vs previous champion over a window; rollback via S3 pointer swap |
| Ephemeral infrastructure lifecycle (spin up / tear down) | Demonstrates cost-awareness and IaC discipline; most demo projects leave resources running indefinitely | MEDIUM | terraform apply in morning, observe all day, terraform destroy in evening; validates the full stack is reproducible |
| Observable retraining cycle within a single day | Crypto regime changes (calm → volatile → calm) make drift observable in hours; demonstrates that the system actually responds to real-world signal | LOW (domain choice) | This is achieved by domain selection, not extra engineering; document explicitly in README |
| W&B experiment comparison across automated runs | Most learners use W&B interactively; running it inside automated Airflow tasks and comparing champion vs challenger programmatically is uncommon | LOW | Log both runs, tag as champion/challenger, compare in W&B UI |
| Prediction logging with backfill for ground truth | Storing predictions at serve time, then computing accuracy after 30-min window closes, demonstrates the ground-truth lag problem production systems face | MEDIUM | Log (timestamp, features, prediction, confidence) to S3 or DynamoDB; compute actuals 30 min later |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Real-time streaming (Kafka, Kinesis) | Sounds production-grade and impressive | Adds 3+ weeks of infrastructure that teaches streaming, not MLOps; 5-min polling teaches the same MLOps concepts with 90% less complexity | Polling every 5 min via Airflow; the loop is fast enough to observe multiple retraining cycles per day |
| Frontend dashboard / custom UI | Visible demo surface; makes it look polished | CloudWatch + W&B + Airflow UI already provide 3 dashboards; building a 4th with React teaches frontend, not MLOps | Use existing CloudWatch and W&B dashboards; screenshot them for portfolio |
| Multi-coin support (ETH, SOL, etc.) | Seems like more coverage | Multiplies infrastructure complexity by N coins without teaching anything new; identical pipeline for each coin | BTC only; the MLOps patterns transfer, the domain doesn't need to scale |
| GPU inference (Triton, TensorRT) | Production ML uses GPUs | XGBoost + ONNX Runtime on CPU is faster than GPU for this model size; GPU infrastructure adds cost and complexity with no accuracy benefit | ONNX Runtime CPU; Lambda + ONNX Runtime cold start is acceptable at 5-min prediction interval |
| MLflow server | Common in tutorials | Requires hosting a server (EC2, RDS) that duplicates W&B's hosted free tier functionality; teaches server maintenance, not MLOps concepts | W&B free tier + S3 JSON backup covers experiment tracking and model registry without hosting |
| Profitable trading signals | Domain extension of the prediction task | Out of scope; this is an MLOps project not a quant project; chasing trading alpha distracts from the infrastructure learning goal | Binary volatility classification is sufficient; accuracy 70-80% is realistic and the drift detection story is compelling regardless of trading profitability |
| Kubernetes / EKS | "Production" container orchestration | Overkill for a single-model, low-QPS serving endpoint; adds 2+ weeks of k8s learning unrelated to MLOps concepts | Lambda + API Gateway; scales to zero (free), cold start acceptable, deploys from ECR |
| LSTM / deep learning model | Better at sequential data | Trains in minutes instead of seconds; makes automated retraining inside Airflow tasks expensive and hard to observe rapidly; ONNX export from PyTorch adds steps | XGBoost; trains in <2 sec, has excellent ONNX export, tabular feature importance is interpretable |
| Separate microservices per MLOps component | Architecturally "clean" | Massively increases deployment complexity for a solo learning project; the value is understanding the concepts, not running 8 services | Airflow handles orchestration; Lambda handles serving; S3 handles storage; keep it flat |
| Canary / blue-green model deployment | Production traffic management | Requires traffic splitting infrastructure (Lambda aliases, weighted routing) that adds 1+ week and is orthogonal to the MLOps learning goal | Champion/challenger evaluation in Airflow before promotion; direct swap of current.onnx when champion wins |

---

## Feature Dependencies

```
[CoinGecko Ingest]
    └──produces──> [Raw OHLCV Data in S3]
                       └──requires──> [Feature Engineering Pipeline]
                                          └──writes──> [Feast Offline Store (S3 Parquet)]
                                          └──materializes──> [Feast Online Store (Redis)]

[Feast Offline Store]
    └──provides training data──> [XGBoost Training + GridSearchCV]
                                     └──produces──> [ONNX Model Artifact]
                                                        └──logged to──> [W&B Experiment Run]
                                                        └──versioned in──> [S3 Model Registry]

[S3 Model Registry]
    └──current.onnx served by──> [FastAPI + ONNX Runtime on Lambda]
                                     └──exposed via──> [API Gateway GET /predict]
                                     └──logs predictions to──> [Prediction Log (S3 / DynamoDB)]

[Prediction Log]
    └──backfilled 30 min later──> [Ground Truth Actuals]
                                      └──enables──> [Rolling Accuracy Monitoring]
                                      └──enables──> [Model Drift Detection]

[Feature Engineering Pipeline]
    └──distribution compared in──> [KS-Test Drift Detection]
                                        └──if drift > threshold──> [Trigger Retraining DAG Branch]
                                        └──if drift < threshold──> [Continue Scheduled Cycle]

[KS-Test Drift Detection] ──enhances──> [Rolling Accuracy Monitoring]
(two complementary signals: input drift + output degradation)

[Airflow DAG]
    └──orchestrates all above──> [ingest → features → predict → retrain → evaluate → promote → monitor]

[GitHub Actions CI/CD]
    └──on PR──> [lint + unit tests]
    └──on merge to main──> [Docker build → ECR push → Lambda update]

[Terraform IaC]
    └──provisions all──> [EC2, RDS, ElastiCache, Lambda, API Gateway, S3, ECR, SNS, CloudWatch]
```

### Dependency Notes

- **Feature Engineering requires Raw Ingest:** No features without data. Ingest must run first in every DAG cycle.
- **Feast Offline Store requires Feature Engineering:** Training data is pulled from Feast offline store; raw OHLCV never feeds the model directly.
- **Feast Online Store requires Feast Offline Store materialization:** Online store is populated by `feast materialize`; it is not computed fresh at serve time.
- **Model Training requires Feast Offline Store:** Training must pull point-in-time correct features from the offline store, not recompute them, to avoid skew.
- **Model Promotion requires W&B Experiment Tracking:** Promotion gate compares metrics from the current challenger run against the champion baseline stored in W&B.
- **Drift Detection requires Feature Engineering history:** KS-test compares current feature distributions against a reference window; reference window is populated by prior feature pipeline runs.
- **Rolling Accuracy requires Prediction Log + Ground Truth Backfill:** Cannot compute accuracy without storing predictions at serve time and waiting 30 min for actuals.
- **Alerting requires both Drift Detection and Rolling Accuracy:** SNS fires on either signal; both must be running for the monitoring loop to be complete.
- **CI/CD requires Docker + ECR:** Lambda is updated by pushing a new container image; ECR must exist before any deployment can happen.
- **Airflow DAG requires RDS (PostgreSQL metadata) and EC2:** Airflow metadata store runs on RDS db.t3.micro; Airflow scheduler runs on EC2 t3.micro.
- **All AWS resources require Terraform:** Ephemeral infrastructure pattern — nothing is manually provisioned.

---

## MVP Definition

### Launch With (v1) — The Minimum That Demonstrates a Real MLOps Loop

The MVP proves the complete cycle: data in → features → train → serve → monitor → retrain → promote, with drift triggering the cycle.

- [ ] CoinGecko ingest + raw OHLCV to S3 — live data is the foundation
- [ ] Feature engineering pipeline (12 features: volatility window, RSI, volume spike, moving averages, Bollinger Bands) — the model's inputs
- [ ] Feast feature store (S3 offline + Redis online) — single source of truth, skew prevention
- [ ] VOLATILE/CALM labeling from future 30-min window — the prediction target
- [ ] XGBoost training with GridSearchCV + ONNX export — the model artifact
- [ ] W&B experiment tracking (metrics, hyperparams, feature importance) — basis for promotion decisions
- [ ] S3 model registry (current.onnx, v{n}.onnx) — versioned artifacts
- [ ] Automated promotion gate (challenger vs champion on held-out eval set) — CT component
- [ ] FastAPI + ONNX Runtime on Lambda (GET /predict, GET /health) — serving
- [ ] API Gateway in front of Lambda — public endpoint
- [ ] Airflow DAG (ingest → features → predict → retrain → evaluate → promote → monitor) — orchestration
- [ ] KS-test data drift detection on feature distributions — event-driven retraining trigger
- [ ] Rolling accuracy monitoring on backfilled actuals — model performance signal
- [ ] SNS alerting on drift or accuracy drop — closes the monitoring loop
- [ ] CloudWatch dashboard (accuracy, drift score, model version, latency) — observability
- [ ] GitHub Actions CI/CD (lint + test on PR; Docker → ECR → Lambda on merge) — code delivery
- [ ] Terraform for all AWS resources — reproducible infrastructure

### Add After Validation (v1.x) — If Time Allows

- [ ] Automated rollback if promoted model degrades rolling accuracy — triggers if rolling accuracy after promotion falls below champion baseline over a 30-min observation window
- [ ] Prediction confidence logging alongside prediction label — enables richer monitoring (low-confidence predictions before drift is detected)
- [ ] W&B champion/challenger run comparison with tags — surfaces the evaluation story visually in W&B UI

### Future Consideration (v2+) — Deliberate Deferrals

- [ ] Drift-triggered retraining (separate from scheduled) as a distinct DAG branch — currently the 30-min schedule subsumes most drift events given crypto's regime-change velocity; this becomes valuable if the schedule is relaxed
- [ ] Multi-feature drift scoring (weighted aggregate KS score across all 12 features vs single-feature alarm) — more robust but adds tuning complexity
- [ ] Evidently AI integration for richer drift reports — replaces manual KS test with a report; adds dependency but improves observability; defer until base monitoring is stable

---

## Feature Prioritization Matrix

| Feature | Learning Value | Implementation Cost | Priority |
|---------|---------------|---------------------|----------|
| Feast feature store (online + offline) | HIGH — skew prevention is the #1 MLOps production concept | HIGH — Redis materialization + S3 offline store setup | P1 |
| Airflow DAG orchestration | HIGH — DAG dependencies + retries = real orchestration | HIGH — EC2 + RDS setup, DAG authoring | P1 |
| KS-test drift detection + retraining trigger | HIGH — demonstrates CT not just cron-based retraining | MEDIUM — scipy + threshold logic | P1 |
| Automated model promotion gate | HIGH — W&B champion vs challenger comparison | MEDIUM — metric comparison logic in Airflow task | P1 |
| FastAPI + ONNX Runtime on Lambda | HIGH — demonstrates production serving patterns | MEDIUM — Lambda container image + API Gateway | P1 |
| GitHub Actions CI/CD | HIGH — code delivery is required for "Ops" claim | MEDIUM — two workflows (PR + merge) | P1 |
| Terraform IaC | HIGH — ephemeral infra lifecycle; reproducibility | HIGH — all AWS resources in Terraform | P1 |
| W&B experiment tracking | HIGH — without it, promotion has no basis | LOW — 5 lines of code integration | P1 |
| Rolling accuracy on backfilled actuals | HIGH — demonstrates ground-truth lag problem | MEDIUM — prediction logging + 30-min backfill | P1 |
| SNS alerting | MEDIUM — closes monitoring loop | LOW — single SNS topic + Airflow trigger | P2 |
| CloudWatch dashboard | MEDIUM — observability surface | LOW — CloudWatch metrics from Lambda + Airflow | P2 |
| Prediction confidence logging | LOW — nice for richer monitoring | LOW — add to prediction log schema | P3 |
| Automated rollback | MEDIUM — safety thinking | MEDIUM — S3 pointer swap + accuracy comparison | P2 |
| W&B champion/challenger tags | LOW — visual story in UI | LOW — add tags to W&B run on promote | P3 |

**Priority key:**
- P1: Must have — the MLOps lifecycle claim fails without it
- P2: Should have — adds completeness and observability without blocking the learning goal
- P3: Nice to have — polish after the core loop is running and observable

---

## Competitor Feature Analysis

For an MLOps learning project, "competitors" are other demo/portfolio MLOps projects. The question is: what makes this one stand out?

| Feature | Typical MLOps Demo | Fraud Detection MLOps (GitHub pattern) | This Project |
|---------|-------------------|----------------------------------------|-------------|
| Data source | Static CSV / Kaggle dataset | Static labeled transactions | Live CoinGecko API — real-time drift |
| Drift observation timeline | Days to weeks | Days to weeks (fraud patterns shift slowly) | Hours — crypto regime changes daily |
| Feature store | Missing in most demos | Often missing | Feast with S3 + Redis (online + offline) |
| Training-serving skew prevention | Absent — recomputed at serve time | Absent | Explicit — single Feast feature definition |
| Automated retraining trigger | Cron schedule only | Cron schedule only | KS-test drift-triggered + scheduled |
| Model format | Raw pickle / joblib | Pickle or ONNX | ONNX only — framework-agnostic |
| Orchestration | Missing or GitHub Actions only | Airflow in better examples | Airflow DAG with 7 dependent tasks |
| Infrastructure | Manual or partial IaC | Partial Docker | Full Terraform; ephemeral lifecycle |
| Cost | Often runs 24/7 on always-on infra | Often always-on | $0 — free tier; spin up / tear down daily |

---

## Sources

- [MLOps Principles — ml-ops.org](https://ml-ops.org/content/mlops-principles) — MEDIUM confidence; canonical MLOps lifecycle reference
- [Google Cloud MLOps: Continuous delivery and automation pipelines](https://docs.cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning) — HIGH confidence; authoritative source on CI/CD/CT/CM pattern
- [Feast Feature Store: Solving Training-Serving Skew (Nov 2025, Medium)](https://medium.com/@scoopnisker/solving-the-training-serving-skew-problem-with-feast-feature-store-3719b47e23a2) — MEDIUM confidence; recent community verification of Feast S3+Redis pattern
- [Feast Practical Operation Guide: Real-time Serving and Skew Prevention (Mar 2026)](https://www.youngju.dev/blog/ai-platform/2026-03-07-ai-platform-feast-feature-store-real-time-serving.en) — MEDIUM confidence; current-month source, confirms online/offline pattern
- [Redis: Building Feature Stores with Feast](https://redis.io/blog/building-feature-stores-with-redis-introduction-to-feast-with-redis/) — HIGH confidence; official Redis engineering blog
- [Evidently AI: Which drift test is best? (comparing KS and others)](https://www.evidentlyai.com/blog/data-drift-detection-large-datasets) — HIGH confidence; authoritative drift detection comparison; confirms KS-test is appropriate for small-medium datasets
- [DeepChecks: Kolmogorov-Smirnov for Enhanced Data Drift Detection](https://www.deepchecks.com/mastering-kolmogorov-smirnov-tests-for-enhanced-data-drift-detection/) — MEDIUM confidence; confirms KS sensitivity limits (most relevant for datasets >100K; our ~288-sample windows are fine)
- [Cryptocurrency Price Forecasting Using XGBoost and Technical Indicators (arXiv 2407.11786)](https://arxiv.org/html/2407.11786v1) — HIGH confidence; peer-reviewed; confirms RSI, MACD, Bollinger Bands, EMA as top features for crypto prediction
- [GitHub Actions for MLOps Pipelines (GitHub Blog)](https://github.blog/enterprise-software/ci-cd/streamlining-your-mlops-pipeline-with-github-actions-and-arm64-runners/) — HIGH confidence; official GitHub blog on MLOps CI/CD patterns
- [MLOps Best Practices: 5 Technical Pillars (DEV Community, 2025)](https://dev.to/apprecode/mlops-best-practices-10-practical-practices-teams-actually-use-h77) — MEDIUM confidence; community-verified alignment with pillars: reproducible pipelines, CI/CD, registries, serving, monitoring

---
*Feature research for: Crypto Volatility MLOps — End-to-End Learning Project*
*Researched: 2026-03-12*
