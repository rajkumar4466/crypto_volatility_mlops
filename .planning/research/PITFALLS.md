# Pitfalls Research

**Domain:** Crypto Volatility MLOps — XGBoost/ONNX on AWS Free Tier (Airflow, Feast, Lambda, W&B, Terraform)
**Researched:** 2026-03-12
**Confidence:** MEDIUM — core pitfalls verified via multiple sources; free-tier specifics verified via AWS re:Post; some threshold values estimated from community experience

---

## Critical Pitfalls

### Pitfall 1: Airflow OOM Kills on t3.micro

**What goes wrong:**
Airflow's scheduler, dag-processor, and worker processes consume more than 1 GB RAM combined. The Linux OOM killer silently terminates the most memory-hungry process — usually a running task or the scheduler — with SIGKILL. The task appears to hang or fails with no useful log message. On a 30-minute retraining schedule, OOM kills cause missed cycles and zombie tasks.

**Why it happens:**
t3.micro has 1 GB RAM. Airflow with LocalExecutor + PostgreSQL metadata requires ~600–800 MB baseline (scheduler + webserver + triggerer). A single Python task that loads XGBoost, runs GridSearchCV, and computes features can consume another 400–600 MB. The total exceeds physical RAM and swap is absent by default on EC2 instances.

**How to avoid:**
Configure swap space on the EC2 instance before installing Airflow — 2 GB swap file is the minimum. Tune Airflow concurrency: set `parallelism = 2`, `max_active_tasks_per_dag = 2`, `max_active_runs_per_dag = 1` in `airflow.cfg`. Keep Python tasks lean: load only what the task needs, release objects explicitly, avoid importing the full feature-engineering library at module load time. Disable Airflow's triggerer component if not using deferrable operators.

**Warning signs:**
- Tasks stuck in "running" state for longer than their expected duration
- Airflow webserver becomes unresponsive
- SSH to instance shows `MemAvailable` near zero in `free -m`
- `dmesg | grep -i "killed process"` shows Airflow components being killed
- DAG runs missing from the UI without explicit failure records

**Phase to address:** Infrastructure setup phase (before any DAGs are deployed)

---

### Pitfall 2: Look-Ahead Bias in Time Series Features and Labels

**What goes wrong:**
The model achieves 85%+ accuracy in training but performs at near-random in production. This is caused by future data leaking into features or labels during training. Common vectors: (1) using `pd.DataFrame.rolling()` without `min_periods`, which back-fills windows; (2) computing the volatility label using the same candle that is the last feature candle; (3) shuffling the dataset before train/test split instead of using a time-ordered split; (4) normalizing features using statistics computed over the entire dataset including the future.

**Why it happens:**
Standard sklearn patterns (random shuffle in `train_test_split`, `StandardScaler.fit_transform` on all data) are designed for i.i.d. data. Time series violates i.i.d. assumptions. Crypto tutorials frequently ignore this because the mistake inflates metrics to exciting numbers.

**How to avoid:**
- Always split time series by index cutoff, never by random shuffle: `X_train = df[df.index < cutoff]`
- The label for candle at time `t` must use only data from time `t+1` through `t+30` — verify this in code with an explicit assertion
- Fit scalers and feature statistics only on training data, then `.transform()` test data
- Use `TimeSeriesSplit` from sklearn for cross-validation instead of `KFold`
- After training, manually inspect the 5 highest-importance features — any feature derived from future prices should be an immediate red flag

**Warning signs:**
- Training accuracy above 80% on 288-sample dataset — likely leakage
- Accuracy collapses from training to live predictions
- Feature importance shows features that are mathematically correlated with the label by construction (e.g., the actual next-30-min return)

**Phase to address:** Feature engineering and model training phase

---

### Pitfall 3: Training-Serving Skew Through Feast Misuse

**What goes wrong:**
Features computed during training differ from features fetched at serving time, producing silent accuracy degradation. The most common form: training uses `get_historical_features()` with offline S3 store, serving uses `get_online_features()` with Redis. If feature view definitions diverge between when features are materialized and when the model was trained, the model receives different distributions.

**Why it happens:**
Feast requires explicit materialization (`feast materialize`) to push features from offline to online store. If materialization is skipped or runs on a different feature view version than training, the online store serves stale or differently-computed features. Additionally, any feature computed outside Feast (e.g., in the DAG task directly) and passed ad-hoc to the model creates a parallel computation path that can diverge.

**How to avoid:**
- Define all 12 features inside Feast feature views — never compute features inline in the serving Lambda
- Run `feast materialize` as part of every retraining DAG run, before the model is promoted
- Verify online store feature timestamps at serving time — if a feature is older than 2x the materialization interval, return a degraded response rather than serving stale features
- Set Feast feature view TTL to at least 2x the materialization cycle (e.g., if materializing every 30 min, set TTL to 70 min)
- Log the feature hash or version alongside every prediction for post-hoc skew diagnosis

**Warning signs:**
- Model accuracy in W&B training runs looks fine but live accuracy degrades
- Feature distributions in CloudWatch diverge from training-time distributions logged in W&B
- Feast online store returns null values at serving time (TTL mismatch)
- Redis memory grows unboundedly (orphaned entity keys from renamed feature views)

**Phase to address:** Feature store integration phase (Feast + Lambda serving integration)

---

### Pitfall 4: AWS Free Tier Cost Overruns from Orphaned Resources

**What goes wrong:**
The project expects $0 cost, but unexpected charges appear for: Elastic IP addresses attached to stopped instances, EBS snapshot retention after EC2 termination, RDS automated backups retained after instance deletion, ElastiCache data tiering charges, NAT Gateway (if accidentally created), or ECR storage exceeding 500 MB. `terraform destroy` does not remove resources created manually via console or CLI.

**Why it happens:**
`terraform destroy` only removes resources tracked in Terraform state. Any resource created manually for debugging — a security group rule, an S3 bucket created via CLI, an Elastic IP — is invisible to Terraform and persists. RDS retains automated snapshots for 7 days by default; these count toward free tier storage. ElastiCache free tier ended for accounts created after July 15, 2025.

**How to avoid:**
- Set AWS billing alerts at $1 and $5 via CloudWatch — do this before any `terraform apply`
- Use `terraform destroy` as the daily teardown ritual, but always follow with a manual audit: `aws ec2 describe-instances`, `aws rds describe-db-instances`, `aws elasticache describe-cache-clusters`, `aws ec2 describe-nat-gateways`
- Tag all resources with `Project=crypto-volatility-mlops` and use a Tag Editor audit after teardown
- In Terraform, set `skip_final_snapshot = true` and `deletion_protection = false` on RDS and ElastiCache
- Never create resources manually in the AWS console during development — always add them to Terraform first
- Verify your AWS account creation date: ElastiCache free tier only applies to accounts created before July 15, 2025

**Warning signs:**
- AWS Cost Explorer shows any non-zero spend in first week
- `terraform destroy` completes but `aws ec2 describe-instances` shows instances still in "stopped" state
- Email from AWS about approaching free tier limits

**Phase to address:** Infrastructure setup (Terraform) — configure billing alerts before any resource creation

---

### Pitfall 5: XGBoost-to-ONNX Export Failures

**What goes wrong:**
The ONNX export step fails or, worse, silently produces a model that predicts correctly on simple inputs but fails on production inputs. Failure modes: (1) missing converter registration for XGBClassifier in sklearn-onnx; (2) opset version mismatch between sklearn-onnx and ONNX Runtime installed in Lambda; (3) GridSearchCV wrapping XGBClassifier — the pipeline includes the CV wrapper, not the fitted estimator; (4) feature names mismatch — XGBoost trained with named features but ONNX model expects positional inputs.

**Why it happens:**
sklearn-onnx does not natively handle XGBClassifier — you must call `update_registered_converter()` from onnxmltools before conversion. The target opset for conversion must be set to the version supported by the ONNX Runtime version pinned in the Lambda container, and these versions drift independently. GridSearchCV's `.best_estimator_` is the correct object to export, not the GridSearchCV object itself.

**How to avoid:**
```python
# Correct export pattern
from onnxmltools.convert.xgboost.operator_converters.XGBoost import convert_xgboost
from skl2onnx.common.data_types import FloatTensorType
from skl2onnx import convert_sklearn
import onnxmltools

update_registered_converter(
    XGBClassifier,
    "XGBoostXGBClassifier",
    calculate_linear_classifier_output_shapes,
    convert_xgboost,
    options={"nocl": [True, False], "zipmap": [True, False, "columns"]},
)

model_to_export = grid_search.best_estimator_  # NOT grid_search itself
initial_type = [("float_input", FloatTensorType([None, 12]))]
onnx_model = convert_sklearn(model_to_export, initial_types=initial_type, target_opset=17)
```
- Pin onnxruntime and sklearn-onnx/onnxmltools to the same versions in both training and Lambda environments
- Add an integration test: load the ONNX model with ONNX Runtime and run inference on a known input immediately after export, before promotion

**Warning signs:**
- Export step raises `Unable to find a shape calculator for type XGBClassifier`
- Export succeeds but ONNX Runtime raises `RuntimeError: target_opset X is higher than supported`
- Lambda predictions return all zeros or all ones regardless of input
- Output shape mismatch between sklearn model and ONNX model

**Phase to address:** Model training and export phase

---

### Pitfall 6: Lambda Cold Start Exceeding API Gateway Timeout

**What goes wrong:**
Lambda cold starts with a heavy ONNX Runtime + FastAPI + Feast dependency bundle take 8–15 seconds. API Gateway has a default 29-second integration timeout, so cold starts do not cause timeouts — but they degrade prediction latency enough to cause the upstream Airflow "predict" task to time out if it uses a short HTTP timeout. More critically: AWS started billing INIT phase time in August 2025, meaning cold starts that previously cost nothing now count against Lambda billing.

**Why it happens:**
ONNX Runtime is ~130 MB. Combined with FastAPI, Feast client, and boto3, the Lambda deployment package easily reaches 200–240 MB (near the 250 MB limit). Large packages take longer to extract on cold start. Lambda INIT phase billing means every cold start now has direct cost implications.

**How to avoid:**
- Slim the Lambda image: install only `onnxruntime-extensions` not full `onnxruntime`, use `--no-deps` where safe
- Load the ONNX model as a module-level global, not inside the handler — the container reuse model keeps it in memory across warm invocations
- Do not instantiate Feast client inside the handler — initialize at module load
- Set Lambda memory to 512 MB minimum (higher memory = more CPU = faster cold start)
- For the prediction task in Airflow DAG, set HTTP timeout to 45 seconds, not the default 10
- Keep Lambda warm via EventBridge scheduled invocations every 5 minutes during active hours (already aligned with the prediction schedule)

**Warning signs:**
- CloudWatch shows `Init Duration` above 5 seconds in Lambda logs
- Airflow "predict" task fails with `ConnectionTimeout` or `ReadTimeout`
- Lambda package size reported by ECR above 200 MB

**Phase to address:** Lambda serving phase

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Compute features inline in Lambda (bypass Feast) | Faster initial implementation | Training-serving skew; features computed twice with different bugs | Never — defeats the purpose of Feast |
| Use SQLite for Airflow metadata | No RDS setup required | LocalExecutor will not run parallel tasks; single task at a time | Development only, switch to PostgreSQL before any DAG runs |
| Hardcode AWS credentials in Airflow connections | Simpler setup | Credentials leak in logs, state files, and git history | Never — use IAM roles on EC2 instance instead |
| Skip ONNX validation test after export | Faster retrain loop | Silent model corruption promoted to production | Never — 3-line test, no excuse to skip |
| Use `random_state=None` in GridSearchCV | Less code | Non-reproducible experiments; W&B runs not comparable across reruns | Never — set `random_state=42` everywhere |
| Materialize Feast features manually instead of in DAG | Simpler first pass | Serving latency spike when materialization is forgotten | Only in Phase 1 local testing, not in deployed DAG |
| Pin dependencies loosely (e.g., `xgboost>=1.7`) | Less maintenance | numpy 2.x breaks Feast; onnxmltools version drift breaks export | Never — pin exact versions in both training and Lambda |

---

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| CoinGecko Free API | Polling every 60 seconds, exceeding 30 req/min rate limit | One API call per Airflow task invocation (every 30 min); cache raw response in S3 before processing |
| CoinGecko Free API | Treating `null` price as `0` in feature computation | Explicitly check for null; raise a pipeline exception rather than propagate NaN into features |
| Feast + Redis | Setting TTL shorter than materialization interval | Set TTL = materialization_interval * 2.5; if 30-min retrain cycle, set TTL = 75 min minimum |
| Feast + Redis | Renaming feature views without cleaning up Redis | Run `feast teardown` before renaming; Redis retains orphaned keys indefinitely |
| Feast + S3 | Missing `feast apply` after changing feature view schema | `feast apply` must run after any schema change; treat it like a DB migration |
| GitHub Actions + ECR + Lambda | Building Docker image with OCI format (default in docker/build-push-action v4+) | Set `provenance: false` and `sbom: false` in build-push-action to force Docker v2 manifest format |
| W&B | Running W&B in offline mode when network is unavailable and forgetting to sync | Set `WANDB_MODE=online` explicitly; add S3 JSON backup as fallback in the same task |
| Terraform + AWS | Running `terraform destroy` and assuming all resources are gone | Always verify with `aws` CLI commands after destroy; check billing for orphaned resources |
| Airflow + RDS PostgreSQL | Using the default `max_connections` on db.t3.micro (default: 87 connections) | Set `sql_alchemy_pool_size = 5`, `sql_alchemy_max_overflow = 10` in Airflow config to stay well under limit |

---

## Performance Traps

Patterns that work at small scale but fail under the project's operational conditions.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| GridSearchCV with large param grid on 288 samples | Retrain task exceeds Airflow task timeout | Limit grid: 2-3 values per hyperparameter; set `n_jobs=1` on t3.micro (parallel jobs cause OOM) | Immediately on t3.micro with any n_jobs > 1 |
| Fetching full OHLCV history on every DAG run | CoinGecko rate limit hit; 5-minute ingestion task | Fetch only the last N candles since last successful run; store watermark in S3 | After a few days of 30-min runs |
| Logging W&B runs inside the Airflow task without timeout | W&B sync failure blocks task completion | Set `wandb.finish(exit_code=0)` with explicit timeout wrapper; always write S3 JSON backup first | On W&B API degradation or network hiccup |
| KS-test on every feature at every DAG run | Alert fatigue — constant retraining, oscillating models | Use KS p-value threshold of 0.01 (not default 0.05); require drift on 3+ features before triggering retrain | On volatile crypto markets — drift will trigger constantly |
| Redis GET for every feature individually during serving | High latency on Lambda warm invocations | Use `get_online_features()` which batches Redis fetches; avoid per-feature individual lookups | At high prediction volume |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Storing AWS credentials in Airflow `airflow.cfg` or connection UI | Credentials exposed in RDS metadata DB and Airflow logs | Use EC2 instance IAM role; never store AWS keys in Airflow connections |
| W&B API key in environment variable without secrets management | Key exposed in EC2 instance metadata, CloudWatch logs | Store W&B key in AWS Secrets Manager or SSM Parameter Store; inject at runtime |
| S3 bucket for model registry with public access | Model weights and feature data publicly readable | Enforce `BlockPublicAccess` on all S3 buckets in Terraform; add S3 bucket policy denying public reads |
| API Gateway endpoint without any auth | Prediction endpoint open to public abuse and cost exploitation | Add API key requirement to API Gateway even for learning project — one line in Terraform |
| CoinGecko API requests without User-Agent header | Increased likelihood of rate limiting or blocking | Set `User-Agent: crypto-volatility-mlops/1.0` in all requests |
| Lambda execution role with `AdministratorAccess` | Full AWS account compromise if Lambda is exploited | Scope Lambda role to: S3 read (model registry bucket), ElastiCache read, CloudWatch write |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Model promotion:** Model is saved to S3 — but is the Lambda function updated to load the new version? Verify Lambda uses `current.onnx` pointer and has loaded the new file after each promotion.
- [ ] **Drift detection:** KS-test code runs — but is the p-value threshold set conservatively enough? A p-value of 0.05 will fire constantly on crypto data; verify threshold is tuned to produce fewer than 3 alerts per day in backtesting.
- [ ] **Feast materialization:** `feast materialize` runs in DAG — but does the Lambda online feature fetch return non-null values immediately after? Add a smoke test HTTP call to Lambda in the DAG after materialization.
- [ ] **ONNX export:** `convert_sklearn()` succeeds — but has the exported model been loaded by ONNX Runtime and run on a test sample? Export success does not guarantee loadable model.
- [ ] **Airflow DAG:** All tasks defined and DAG parses — but do tasks have retry logic and failure callbacks? Verify `retries=2`, `on_failure_callback=sns_alert` on every task.
- [ ] **Terraform destroy:** `terraform destroy` exits 0 — but are there orphaned resources? Always verify with AWS CLI checks for EC2, RDS, ElastiCache, NAT Gateways, and Elastic IPs after destroy.
- [ ] **CI/CD pipeline:** GitHub Actions workflow passes — but does it actually deploy the new Lambda image? Verify the Lambda function ARN in workflow matches the Terraform-managed function, not a stale manual version.
- [ ] **W&B tracking:** Runs appear in W&B dashboard — but is the S3 JSON backup also written? W&B free tier doesn't guarantee data retention; the backup is the source of truth.

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| OOM kill on Airflow t3.micro | LOW | SSH in, add 2 GB swap (`sudo fallocate -l 2G /swapfile`), restart Airflow services, resume failed DAG run |
| Look-ahead bias discovered post-training | HIGH | Re-examine all feature computation code, enforce time-ordered split, retrain from scratch, purge all W&B runs from contaminated experiment |
| Training-serving skew from Feast misuse | MEDIUM | Identify which features diverge (compare offline vs online feature values), re-run `feast materialize` with corrected feature views, deploy corrected Lambda |
| AWS unexpected charges | MEDIUM | Identify resource via Cost Explorer, use `terraform import` to bring it under state management, add to `terraform destroy` workflow, dispute charge with AWS Support if under $10 |
| XGBoost ONNX export failure in production DAG | LOW | DAG should catch export failure and retain previous `current.onnx`; fix opset version mismatch in Dockerfile, redeploy Lambda |
| Lambda cold start causing Airflow task timeout | LOW | Increase Airflow task HTTP timeout to 60 seconds, add EventBridge keep-warm invocation every 4 minutes |
| Orphaned Redis keys from renamed Feast feature views | MEDIUM | Connect to Redis via `redis-cli -h <elasticache-endpoint>`, run `FLUSHDB` (acceptable for this project scale), re-run `feast materialize` |
| Terraform state drift after manual console changes | MEDIUM | Run `terraform plan` to identify drift, use `terraform import` to reconcile manual changes into state, never make manual changes again |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Airflow OOM on t3.micro | Phase: Infrastructure setup (Terraform + EC2 bootstrap) | `free -m` shows >2 GB swap; Airflow scheduler runs for 30 min without OOM kills |
| Look-ahead bias | Phase: Feature engineering and model training | Unit test: assert train/test split by index; integration test: accuracy on time-ordered holdout |
| Training-serving skew | Phase: Feast + Lambda serving integration | Smoke test: compare offline feature values to online feature values for same entity |
| AWS free tier cost overruns | Phase: Infrastructure setup (before any `terraform apply`) | Billing alert at $1 configured; `terraform destroy` verified by CLI audit |
| XGBoost ONNX export failures | Phase: Model training and export | Integration test runs ONNX model on known input immediately after every export |
| Lambda cold start latency | Phase: Lambda serving phase | CloudWatch `Init Duration` metric below 5 seconds; Airflow predict task uses 60-second timeout |
| CoinGecko rate limiting | Phase: Data ingestion DAG | Ingest task uses a single API call per run; error handling on HTTP 429 with exponential backoff |
| Drift detection false positives | Phase: Monitoring and alerting | Backtest drift thresholds on historical data; alert rate below 3 per day on typical market conditions |
| Feast Redis TTL staleness | Phase: Feast integration | Online feature fetch smoke test after each materialization; TTL set to 2.5x materialization interval |
| GitHub Actions OCI format error | Phase: CI/CD pipeline | Docker image built with `provenance: false`; Lambda update step verified in integration environment |

---

## Sources

- [Airflow memory leak issues (2025) — apache/airflow GitHub issues #56641, #58509](https://github.com/apache/airflow/issues/56641)
- [Airflow OOM worker crashes — apache/airflow GitHub issues #10717, #16703](https://github.com/apache/airflow/issues/10717)
- [Choosing EC2 instance for Airflow (t3.micro too small)](https://medium.com/@bettercallkevinar/choosing-the-right-ec2-instance-for-deploying-apache-airflow-on-aws-4c35b39bac85)
- [Machine Learning & Volatility Forecasting: Avoiding the Look-Ahead Trap](https://medium.com/@contact_9367/machine-learning-volatility-forecasting-avoiding-the-look-ahead-trap-6ff63c8c703c)
- [Data Leakage in Time Series ML — Springer Nature (2025)](https://link.springer.com/article/10.1007/s10614-025-11172-z)
- [Feast training-serving skew prevention guide (2026)](https://www.youngju.dev/blog/ai-platform/2026-03-07-ai-platform-feast-feature-store-real-time-serving.en)
- [Feast Redis TTL staleness — feast-dev/feast issue #3596](https://github.com/feast-dev/feast/issues/3596)
- [Feast Redis TTL entity expiration — feast-dev/feast issue #1988](https://github.com/feast-dev/feast/issues/1988)
- [AWS Free Tier unexpected EC2 charges — AWS re:Post](https://repost.aws/questions/QUxy1gpLOzSgm2TZ1cUCjzEw/why-am-i-seeing-unexpected-ec2-charges-beyond-free-tier)
- [AWS Free Tier RDS charges — AWS re:Post](https://repost.aws/questions/QUTKRiS9LKT-a8P0kI2svm2g/free-tier-rds-has-been-charged)
- [Understanding unexpected AWS charges — AWS Billing docs](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/checklistforunwantedcharges.html)
- [sklearn-onnx XGBoost converter registration — onnx.ai docs](https://onnx.ai/sklearn-onnx/auto_tutorial/plot_gexternal_xgboost.html)
- [XGBoost ONNX export opset errors — onnx/sklearn-onnx issue #829](https://github.com/onnx/sklearn-onnx/issues/829)
- [AWS Lambda Cold Starts INIT billing (August 2025)](https://edgedelta.com/company/knowledge-center/aws-lambda-cold-start-cost)
- [Lambda ONNX serving guide — PyImageSearch (2025)](https://pyimagesearch.com/2025/11/03/introduction-to-serverless-model-deployment-with-aws-lambda-and-onnx/)
- [CoinGecko free API rate limits — CoinGecko docs](https://docs.coingecko.com/docs/common-errors-rate-limit)
- [CoinGecko null data field handling — CoinGecko API troubleshooting](https://www.coingecko.com/learn/coingecko-api-troubleshooting-guide-and-solutions)
- [Airflow LocalExecutor requires PostgreSQL — Airflow official docs](https://airflow.apache.org/docs/apache-airflow/stable/howto/set-up-database.html)
- [KS drift detection window size pitfalls (2025)](https://towardsdatascience.com/how-to-detect-model-drift-in-mlops-monitoring-7a039c22eaf9/)
- [Terraform destroy stuck on AWS dependencies](https://rakeshkadam.medium.com/when-terraform-destroy-gets-stuck-debugging-aws-resource-dependencies-a630fc432ddd)
- [GitHub Actions ECR OCI format Lambda incompatibility](https://dev.to/aws-builders/fix-invalidparametervalueexception-for-aws-lambda-docker-images-built-by-github-actions-32p9)
- [EC2 swap space for Airflow on micro instances](https://www.w3tutorials.net/blog/how-do-you-add-swap-to-an-ec2-instance/)
- [numpy 2.x breaking Feast — Feast community (2025)](https://medium.com/@scoopnisker/solving-the-training-serving-skew-problem-with-feast-feature-store-3719b47e23a2)

---
*Pitfalls research for: Crypto Volatility MLOps on AWS Free Tier*
*Researched: 2026-03-12*
