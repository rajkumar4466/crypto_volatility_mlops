# Project Research Summary

**Project:** Crypto Volatility MLOps
**Domain:** End-to-end ML pipeline with full MLOps infrastructure on AWS free tier
**Researched:** 2026-03-12
**Confidence:** MEDIUM

## Executive Summary

This project is a portfolio-grade MLOps system that demonstrates the complete Continuous Training (CT) loop: live data ingestion → feature engineering → model training → serving → monitoring → drift-triggered retraining. The recommended approach follows the FTI (Feature / Training / Inference) pipeline decomposition pattern, where three independently operable pipelines share a Feast feature store as their single source of truth. The domain choice — BTC volatility prediction from live CoinGecko OHLCV data — is a deliberate enabler: crypto markets shift regimes within hours, making drift observable and the retraining loop exercisable multiple times per day rather than waiting days or weeks.

The recommended stack runs entirely on AWS free tier at $0 cost using a spin-up/tear-down Terraform lifecycle. XGBoost (trained in <2 seconds on 288 samples) converts to ONNX via onnxmltools and is served by ONNX Runtime inside a Lambda container. Airflow on a t3.micro EC2 instance orchestrates the DAG; Feast (S3 offline + ElastiCache Redis online) enforces the single feature definition that prevents training-serving skew; W&B tracks experiments; GitHub Actions provides CI/CD. The ephemeral infrastructure pattern — `terraform apply` in the morning, `terraform destroy` in the evening — keeps all time-limited free-tier resources well within their monthly allowances.

The dominant risk in this project is not algorithmic complexity but operational correctness: Airflow OOM kills on t3.micro, training-serving skew through Feast misuse, look-ahead bias in time-series labels, and XGBoost-to-ONNX export failures are all silent failure modes that produce plausible-looking but wrong results. Every phase must include explicit verification steps — not just "it runs" but "it produces the expected output." Python 3.11 is the required runtime for all-package compatibility; EC2 swap space must be configured before Airflow is installed; billing alerts must be set before any `terraform apply`.

---

## Key Findings

### Recommended Stack

The stack is fully open-source and free-tier compatible. Python 3.11 is the required runtime (hard lower bound from pandas 3.0.1, scipy 1.17.1, scikit-learn 1.8.0, and Airflow 3.1.8). XGBoost 3.x has no native ONNX export; conversion requires onnxmltools 1.16.0 + skl2onnx 1.20.0. Lambda container images (up to 10GB) are the correct deployment unit — ZIP packages cannot fit onnxruntime (~130MB) within the 250MB uncompressed limit.

**Core technologies:**
- **XGBoost 3.2.0** (ML core): Binary classifier; trains in <2 seconds on 288 samples; best tabular accuracy among tree methods; ONNX ecosystem support via onnxmltools
- **onnxmltools 1.16.0 + skl2onnx 1.20.0** (ONNX export): Required pair; XGBoost 3.x has no native ONNX export; `grid_search.best_estimator_` is the correct export target, not the GridSearchCV wrapper
- **onnxruntime 1.24.3** (inference): CPU-only, ~13MB, sub-millisecond latency on XGBoost-scale models; use x86_64 Lambda to avoid ARM64 `Illegal instruction` bug
- **FastAPI 0.135.1 + Mangum** (serving API): Minimal ASGI overhead; Mangum adapts FastAPI to Lambda event format
- **Feast 0.61.0** (feature store): S3 offline + Redis online; single feature definition eliminates training-serving skew; file-based S3 registry sufficient at this scale
- **Apache Airflow 3.1.8** (orchestration): Full DAG dependency management with retries and UI; requires RDS PostgreSQL — SQLite is explicitly unsupported for production use
- **W&B 0.25.1** (experiment tracking): Free hosted dashboard; no server to maintain; programmatic champion/challenger comparison inside Airflow tasks
- **Terraform 1.14.7** (IaC): Declarative AWS resource definitions; `terraform destroy` enables clean daily teardown
- **AWS Lambda + API Gateway + S3 + EC2 t3.micro + RDS db.t3.micro + ElastiCache cache.t3.micro** (infrastructure): All free-tier eligible; ElastiCache free tier only applies to accounts created before July 15, 2025

See `/Users/mithra_sundaram/Desktop/code/models/crypto_volatility_mlops/.planning/research/STACK.md` for full version matrix and compatibility table.

### Expected Features

The MLOps lifecycle claim is credible only if all P1 features are present. Missing any one of them degrades the project to "a notebook with a deploy script."

**Must have — P1 (table stakes):**
- Live CoinGecko OHLCV ingest (5-min polling, no API key required)
- 12-feature engineering pipeline (RSI, volatility window, volume spike, MAs, Bollinger Bands) — computed once in Feast, consumed identically at train and serve time
- Feast feature store (S3 offline + Redis online) — training-serving skew prevention is the core learning outcome
- VOLATILE/CALM binary labeling from future 30-min window — must not leak future data
- XGBoost GridSearchCV training + ONNX export + W&B tracking
- S3 model registry (current.onnx + versioned artifacts)
- Automated promotion gate (challenger vs champion on held-out eval set)
- FastAPI + ONNX Runtime on Lambda (GET /predict, GET /health)
- Airflow DAG with 7 dependent tasks (ingest → features → predict → retrain → evaluate → promote → monitor)
- KS-test drift detection on feature distributions — triggers retraining
- Rolling accuracy monitoring on backfilled actuals (30-min ground-truth lag)
- SNS alerting on drift or accuracy drop
- CloudWatch dashboard (accuracy, drift score, model version, latency)
- GitHub Actions CI/CD (lint + test on PR; Docker → ECR → Lambda on merge)
- Terraform for all AWS resources

**Should have — P2 (completeness):**
- Automated rollback if promoted model degrades rolling accuracy below champion baseline
- CloudWatch billing alerts at $1 and $5 (required before any terraform apply)

**Defer — v2+:**
- Drift-triggered retraining as a separate DAG branch (30-min schedule subsumes most drift events given crypto's regime velocity)
- Multi-feature weighted drift scoring (Evidently AI integration)
- Real-time streaming (Kafka/Kinesis), multi-coin support, custom UI, GPU inference, Kubernetes — all anti-features for this learning scope

See `/Users/mithra_sundaram/Desktop/code/models/crypto_volatility_mlops/.planning/research/FEATURES.md` for full feature dependency graph and prioritization matrix.

### Architecture Approach

The system is decomposed into three independently deployable FTI pipelines coupled only through the Feast feature store. The Feature Pipeline (CoinGecko → 12 features → Feast offline S3 → Feast online Redis) is the only component that touches raw data. The Training Pipeline (Feast offline → XGBoost GridSearchCV → ONNX → W&B → S3 registry → promotion gate) never recomputes features. The Inference Pipeline (API Gateway → Lambda → Feast online → ONNX Runtime → CloudWatch) never trains models. Airflow on EC2 orchestrates all three. This architecture makes training-serving skew structurally impossible if implemented correctly.

**Major components:**
1. **Feast Feature Store (S3 + Redis)** — single source of truth; offline store for point-in-time training data; online store for <10ms serving lookups; materialization is the only data path from batch to real-time
2. **Airflow DAG (EC2 + RDS)** — master orchestrator; 7-task dependency chain with retries; drift detection task can branch to immediate retraining via Airflow REST API
3. **Lambda + ONNX Runtime** — serverless serving; model loaded at module level (not inside handler) to cache across warm invocations; VPC required to reach ElastiCache Redis
4. **S3 Model Registry** — `current.onnx` pointer pattern; `current_metrics.json` stores champion metrics for promotion gate comparison
5. **KS-test Drift Detector** — `scipy.stats.ks_2samp` on recent vs reference feature distributions; p-value threshold of 0.01 (not 0.05) to avoid alert fatigue on volatile crypto data
6. **Terraform + GitHub Actions** — ephemeral infrastructure lifecycle; all resources codified; CI/CD prevents manual drift

**Build order (hard dependencies):** Terraform → Feast definitions → Feature pipeline → Training pipeline → Lambda serving → Airflow DAG → Monitoring → CI/CD. Do not wire up Airflow until each component is verified working in isolation.

See `/Users/mithra_sundaram/Desktop/code/models/crypto_volatility_mlops/.planning/research/ARCHITECTURE.md` for full component diagram, data flow sequences, and anti-pattern catalog.

### Critical Pitfalls

1. **Airflow OOM kills on t3.micro** — Configure 4GB EBS swap before installing Airflow; set `parallelism=2`, `max_active_tasks_per_dag=2`; keep task memory footprints small with `n_jobs=1` in GridSearchCV; set billing alert at $1 before any EC2 creation
2. **Look-ahead bias in time-series features/labels** — Always split by index cutoff (never random shuffle); label at time `t` uses only data from `t+1` through `t+30`; use `TimeSeriesSplit` for cross-validation; fit scalers on training split only; training accuracy above 80% on 288 samples is a leakage red flag
3. **Training-serving skew through Feast misuse** — Define all 12 features inside Feast feature views; never compute features inline in Lambda; run `feast materialize` in every retraining DAG cycle before promotion; set TTL = 2.5x materialization interval; run smoke test after each materialization
4. **XGBoost-to-ONNX export failures** — Export `grid_search.best_estimator_` (not the GridSearchCV wrapper); call `update_registered_converter()` before `convert_sklearn()`; pin onnxruntime and skl2onnx to identical versions in both training and Lambda environments; always run ONNX Runtime inference on a known input immediately after export before promotion
5. **AWS free tier cost overruns from orphaned resources** — Set billing alerts at $1 and $5 before any `terraform apply`; use `terraform destroy` daily followed by manual AWS CLI audit; set `skip_final_snapshot=true` and `deletion_protection=false` on RDS and ElastiCache in Terraform; never create resources via console; verify ElastiCache free tier eligibility by account creation date

See `/Users/mithra_sundaram/Desktop/code/models/crypto_volatility_mlops/.planning/research/PITFALLS.md` for full pitfall catalog, integration gotchas, and recovery strategies.

---

## Implications for Roadmap

The architecture's build order graph drives phase sequencing. Each phase has hard dependencies on the previous phase's outputs. Do not advance to the next phase until the current phase's verification criteria are met in isolation — debugging a broken Airflow DAG with five failing tasks is exponentially harder than debugging each task as a standalone script.

### Phase 1: Infrastructure Foundation
**Rationale:** Everything else runs in AWS. Terraform must exist and billing alerts must be configured before any other work begins. This phase has no application code — it is purely infrastructure.
**Delivers:** All AWS resources provisioned (EC2, RDS, ElastiCache, Lambda stub, S3, ECR, API Gateway, SNS, CloudWatch); billing alerts at $1 and $5; `terraform destroy` verified by CLI audit; daily spin-up/tear-down workflow documented
**Addresses:** IaC requirement (P1 feature); ephemeral infrastructure lifecycle (differentiator)
**Avoids:** AWS free tier cost overruns; Terraform state drift from manual console changes
**Note:** Configure EC2 swap (4GB) in the Terraform user-data bootstrap script, not manually after the fact

### Phase 2: Data Ingestion and Feature Pipeline
**Rationale:** The feature store must be populated before training can run. Feast feature view definitions must be written before any features are stored. This phase establishes the single source of truth.
**Delivers:** CoinGecko OHLCV ingest to S3 raw store; 12-feature computation + VOLATILE/CALM labeling; Feast offline store (S3 Parquet) populated; Feast online store (Redis) materialized; feature pipeline verified in isolation as a standalone script before DAG integration
**Addresses:** Live data ingest (P1); 12-feature engineering (P1); Feast feature store (P1); single feature definition (differentiator)
**Avoids:** Look-ahead bias (verify time-ordered split and label window in unit tests here); training-serving skew (Feast as single definition source)
**Research flag:** Feast S3 offline store + Redis materialization integration has MEDIUM confidence; verify `feast apply` schema migration behavior during implementation

### Phase 3: Model Training, Export, and Registry
**Rationale:** Depends on Feast offline store having data. Training pipeline is the most failure-prone phase (ONNX export correctness, promotion gate logic, W&B integration). Must be verified standalone before Airflow integration.
**Delivers:** XGBoost GridSearchCV training; ONNX export via onnxmltools (with `update_registered_converter` pattern); W&B experiment tracking with metrics/hyperparams/feature importances; S3 model registry (`current.onnx` + versioned artifacts); automated promotion gate comparing challenger vs champion metrics; ONNX Runtime smoke test after every export
**Addresses:** Model training (P1); ONNX export (P1); W&B tracking (P1); automated promotion (P1)
**Avoids:** XGBoost ONNX export failures (export `best_estimator_`, not GridSearchCV wrapper; always run post-export validation); blindly overwriting current.onnx without metric comparison

### Phase 4: Lambda Serving and API
**Rationale:** Depends on S3 model registry having `current.onnx` and Redis having materialized features. Lambda serving is where training-serving skew manifests — this is the critical integration point between Training and Inference pipelines.
**Delivers:** FastAPI + ONNX Runtime Lambda container (model loaded at module level, not inside handler); API Gateway GET /predict + GET /health endpoints; Feast online feature lookup from ElastiCache Redis within Lambda VPC; CloudWatch latency metrics; prediction logging to S3 (for rolling accuracy computation)
**Addresses:** REST serving (P1); prediction logging with ground-truth lag (differentiator)
**Avoids:** Model loading inside Lambda handler (performance trap); Lambda cold start exceeding API Gateway timeout (set 512MB memory minimum; HTTP timeout in Airflow predict task = 60 seconds); ARM64 ONNX Runtime bug (use x86_64 Lambda)
**Research flag:** Lambda VPC configuration for ElastiCache access requires specific subnet and security group settings; verify during implementation

### Phase 5: Airflow DAG Orchestration
**Rationale:** Airflow wraps all previously verified standalone components into a DAG. Only integrate after Phases 2-4 are working in isolation. The DAG is not where debugging happens — it is where verified components are scheduled and sequenced.
**Delivers:** Single Airflow DAG (ingest → features → predict → retrain → evaluate → promote → monitor); RDS PostgreSQL as Airflow metadata store; retries=2 and on_failure_callback=sns_alert on every task; 30-minute schedule with drift-triggered branch via Airflow REST API; SequentialExecutor to manage t3.micro memory pressure
**Addresses:** DAG orchestration (P1)
**Avoids:** Airflow OOM kills (swap configured in Phase 1; n_jobs=1 in GridSearchCV; lean task footprints); SQLite as metadata store (RDS provisioned in Phase 1)
**Note:** Test each DAG task individually with `airflow tasks test` before running the full DAG

### Phase 6: Monitoring, Drift Detection, and Alerting
**Rationale:** Monitoring depends on serving (prediction logs) and feature data (drift reference window). Both must be running before monitoring is meaningful. This phase closes the CT loop: drift detected → retrain triggered → model promoted.
**Delivers:** KS-test drift detection (p-value threshold 0.01, not 0.05, to reduce false positives on volatile crypto data; alert only if 2+ features drift); rolling accuracy computation on backfilled actuals (30-min lag); SNS email alerts on drift or accuracy drop; CloudWatch dashboard (accuracy, drift score, model version, latency); drift trigger wired to Airflow REST API
**Addresses:** Drift detection (P1); rolling accuracy (P1); SNS alerting (P1); CloudWatch dashboard (P1)
**Avoids:** Drift detection false positives causing constant retraining (tune threshold against historical data before wiring to retrain trigger); KS-test alert fatigue

### Phase 7: CI/CD Pipeline
**Rationale:** CI/CD is built last because it requires all components to exist and the Docker image to be stable. Adding CI/CD during component development would require constant pipeline updates as the image changes.
**Delivers:** GitHub Actions CI workflow (lint with ruff + black; pytest on PR); GitHub Actions CD workflow (Docker build → ECR push with `provenance: false` to avoid OCI format issue → Lambda update via Terraform apply on merge to main); IAM OIDC trust for GitHub Actions → ECR push
**Addresses:** CI/CD pipeline (P1)
**Avoids:** GitHub Actions OCI format Lambda incompatibility (set `provenance: false`, `sbom: false` in build-push-action); deploying to stale manually-created Lambda function (Lambda ARN in workflow must match Terraform-managed function)

### Phase Ordering Rationale

- **Terraform first:** Every AWS resource is provisioned declaratively before any application code runs. Console-created resources break `terraform destroy` and defeat the ephemeral lifecycle pattern.
- **Feature pipeline before training:** Feast offline store must have data before training can pull point-in-time features. Feature definitions must be written before features are stored.
- **Training before serving:** Lambda needs `current.onnx` in S3 and materialized features in Redis before it can serve predictions.
- **Serving before Airflow DAG:** The DAG orchestrates verified standalone scripts. Debug each component in isolation first.
- **DAG before monitoring:** Monitoring needs predictions flowing (for rolling accuracy) and feature history (for drift reference window).
- **CI/CD last:** The Docker image must be stable before adding CI/CD automation over it.

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 2 (Feast integration):** `feast apply` schema migration behavior, `feast materialize_incremental` timing, and S3 offline store path configuration have MEDIUM confidence in research. Validate against Feast 0.61.0 changelog before implementation.
- **Phase 4 (Lambda + VPC + ElastiCache):** Lambda VPC subnet and security group configuration for ElastiCache access is a known complexity point. Verify required VPC settings and potential cold start impact from VPC attachment.
- **Phase 6 (Drift threshold tuning):** KS-test p-value threshold of 0.01 and "2+ features" alert rule are estimated from community experience, not a documented standard. Backtest against historical BTC OHLCV data to calibrate before wiring to retrain trigger.

**Phases with standard, well-documented patterns (can skip research-phase):**
- **Phase 1 (Terraform + AWS):** AWS free-tier resource provisioning via Terraform is extremely well-documented. Verified versions and free-tier limits in research.
- **Phase 3 (XGBoost + ONNX + W&B):** All version-pinned packages verified on PyPI. ONNX export pattern is documented on onnx.ai. W&B integration is 5 lines.
- **Phase 7 (GitHub Actions CI/CD):** Standard Docker + ECR + Lambda deployment pattern; only notable gotcha (OCI format flag) is documented.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified on PyPI 2026-03-12; version compatibility matrix confirmed; AWS free-tier limits verified via official AWS docs and re:Post |
| Features | MEDIUM | MLOps lifecycle components well-documented; crypto-specific MLOps integration verified via cross-source agreement rather than single authoritative source |
| Architecture | MEDIUM | FTI decomposition pattern is well-established; free-tier AWS constraint combinations (EC2 + RDS + ElastiCache + Lambda in same VPC) have limited direct verification |
| Pitfalls | MEDIUM | Core pitfalls verified via multiple sources including GitHub issues and official Airflow/Feast docs; some threshold values (KS p-value, swap size) estimated from community experience |

**Overall confidence:** MEDIUM

### Gaps to Address

- **ElastiCache free tier eligibility:** ElastiCache free tier expired for accounts created after July 15, 2025. Verify account creation date before committing to Redis as the Feast online store. Alternative: Feast SQLite online store (acceptable at this scale, though not production-equivalent).
- **Lambda VPC cold start overhead:** Attaching Lambda to a VPC (required for ElastiCache access) adds cold start latency. Research found no current measurement for onnxruntime 1.24.3 + Feast 0.61.0 in VPC Lambda. Measure `Init Duration` in CloudWatch during Phase 4 and adjust memory allocation if needed.
- **KS-test drift threshold calibration:** The 0.01 p-value threshold and "2+ features" rule are community-estimated, not validated. Backtest during Phase 6 before wiring to retrain trigger to avoid either alert fatigue or missed drift events.
- **Airflow 3.1.8 memory profile on t3.micro:** Airflow 3.x scheduler memory has changed from 2.x; the 600-800MB baseline estimate comes from 2.x reports. Measure actual memory consumption during Phase 5 development and adjust swap allocation if needed.
- **W&B free tier data retention:** W&B free tier guarantees are from their marketing page (MEDIUM confidence). S3 JSON backup is the hedge; treat it as the source of truth, not W&B, for promotion decisions.

---

## Sources

### Primary (HIGH confidence)
- PyPI package pages for all pinned versions — xgboost, onnxruntime, onnxmltools, skl2onnx, fastapi, feast, wandb, apache-airflow, pandas, scipy, scikit-learn (verified 2026-03-12)
- Terraform install page — v1.14.7
- XGBoost Python API docs — confirmed no native ONNX export in `save_model()`
- AWS Lambda limits — 10GB container, 1M invocations free
- AWS EC2 free tier — t3.micro only
- AWS ElastiCache pricing — provisioned t3.micro eligible; Serverless excluded
- Airflow prerequisites docs — 4GB RAM recommended, SQLite dev-only
- sklearn-onnx XGBoost converter registration — onnx.ai official docs
- Google Cloud MLOps architecture — CI/CD/CT/CM pattern authority
- Redis engineering blog — Feast + Redis feature store architecture
- Evidently AI drift detection comparison — KS-test appropriate for small-medium datasets
- Astronomer Airflow MLOps best practices — official Astronomer docs
- GitHub blog — MLOps CI/CD with GitHub Actions

### Secondary (MEDIUM confidence)
- Feast official docs (docs.feast.dev) — feature view TTL, materialization patterns
- AWS ElastiCache + Feast blog — ultra-low latency online feature store pattern
- Hopsworks FTI Pipeline Architecture — FTI decomposition pattern
- ONNX + Lambda + FastAPI pattern (PyImageSearch 2025) — serving integration
- AWS MLOps Drift Detection + CloudWatch (SageMaker-specific but pattern applies)
- Feast Practical Operation Guide (March 2026) — online/offline pattern, current-month source
- Springer Nature 2025 — data leakage in time series ML
- arXiv 2407.11786 — RSI, MACD, Bollinger Bands as top crypto prediction features
- CoinGecko free API docs — 30 req/min rate limit, null field handling
- AWS re:Post — free tier unexpected charges
- GitHub Issues: Airflow OOM, Feast Redis TTL, sklearn-onnx XGBoost export, GitHub Actions ECR OCI format

### Tertiary (LOW confidence)
- Medium post — Solving Training-Serving Skew with Feast (Nov 2025, unverified author)
- Medium post — MLOps on AWS practical architecture (unverified author)
- KS drift threshold estimates — community experience, not documented standard

---
*Research completed: 2026-03-12*
*Ready for roadmap: yes*
