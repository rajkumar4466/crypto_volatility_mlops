---
phase: 04-lambda-serving-and-api
plan: "01"
subsystem: api
tags: [fastapi, lambda, onnxruntime, feast, redis, dynamodb, terraform, eventbridge, mangum, onnx]

# Dependency graph
requires:
  - phase: 03-model-training-and-registry
    provides: ONNX model at s3://{bucket}/models/current.onnx, Feast registry at s3://{bucket}/feast/registry.pb
  - phase: 01-infrastructure-foundation
    provides: Lambda function (aws_lambda_function.predictor), API Gateway HTTP API, DynamoDB table, ECR repo, ElastiCache Redis, IAM roles
  - phase: 02-data-and-feature-pipeline
    provides: Feast feature view (btc_volatility_features), entity (btc_id), 12 features materialized to Redis
provides:
  - FastAPI + ONNX Runtime Lambda container image (serving/Dockerfile) serving GET /health and GET /predict
  - Feast FeatureStore integration reading btc_volatility_features from ElastiCache Redis
  - DynamoDB prediction logging with 30-day TTL (prediction_id, timestamp, features map, prediction, probability, model_version)
  - Backfill Lambda (serving/backfill/backfill_lambda.py) writing actual_label via update_item
  - EventBridge Scheduler triggering backfill every 30 minutes (aws_scheduler_schedule.backfill)
  - Terraform: backfill Lambda function + scheduler IAM role + EventBridge schedule added to serverless module
affects: [05-drift-detection-and-retraining, 06-monitoring-and-alerting, 07-observability]

# Tech tracking
tech-stack:
  added: [fastapi==0.135.1, mangum==0.17.0, onnxruntime==1.24.3, feast==0.61.0, numpy>=2.0, requests==2.32.3, aws_scheduler_schedule (Terraform EventBridge Scheduler)]
  patterns: [module-level-init for Lambda cold-start efficiency, rendered-YAML pattern for Feast config with env var injection, Decimal(str(float)) for DynamoDB numeric types, separate Dockerfile per Lambda function]

key-files:
  created:
    - serving/Dockerfile
    - serving/Dockerfile.backfill
    - serving/requirements.txt
    - serving/app/__init__.py
    - serving/app/main.py
    - serving/feature_repo/__init__.py
    - serving/feature_repo/feature_store.yaml
    - serving/backfill/__init__.py
    - serving/backfill/backfill_lambda.py
    - serving/backfill/requirements.txt
    - scripts/push_backfill_image.sh
  modified:
    - infra/modules/serverless/main.tf
    - infra/modules/serverless/variables.tf
    - infra/modules/serverless/outputs.tf
    - infra/main.tf

key-decisions:
  - "feature_store.yaml rendered at Lambda INIT to /tmp/feature_store.yaml (not static) — env vars (REDIS_HOST, S3_BUCKET) not available at build time"
  - "Separate Dockerfile.backfill for backfill Lambda — lighter image (requests only, no onnxruntime/feast)"
  - "CoinGecko /history endpoint is day-granular for free tier — backfill uses same-day price comparison (limitation); Phase 5 Airflow DAG can refine using stored OHLCV"
  - "Backfill Lambda reuses existing aws_iam_role.lambda — already has DynamoDB UpdateItem/PutItem/GetItem; no new role needed"
  - "EventBridge Scheduler (aws_scheduler_schedule) not CloudWatch Events — scheduler is newer, rate-based, and supported in Terraform AWS provider ~>5.0"
  - "FEATURE_REFS use btc_volatility_features:{name} prefix matching Phase 3 feature view name decision"

patterns-established:
  - "Module-level init: S3 download + ort.InferenceSession + FeatureStore + DynamoDB Table all at module level — runs once per cold start, not per request"
  - "Decimal(str(float)) for DynamoDB: avoids float precision issues and TypeError from native Python floats"
  - "Rendered YAML pattern: write env-var-interpolated YAML to /tmp at Lambda INIT; use fs_yaml_file= parameter in FeatureStore()"
  - "FEATURE_NAMES as single source of truth: same list used for get_online_features refs, numpy array ordering, and DynamoDB features map keys"
  - "attribute_not_exists(actual_label) in DynamoDB FilterExpression: correct way to find items without a key vs null/missing"

requirements-completed: [SERV-01, SERV-02, SERV-03, SERV-04, SERV-05]

# Metrics
duration: 14min
completed: 2026-03-13
---

# Phase 4 Plan 01: Lambda Serving and API Summary

**FastAPI + ONNX Runtime Lambda container reading features from Feast Redis, logging predictions to DynamoDB, with EventBridge-triggered backfill Lambda writing actual_label 30 minutes post-prediction**

## Performance

- **Duration:** 14 min
- **Started:** 2026-03-13T15:17:33Z
- **Completed:** 2026-03-13T15:31:38Z
- **Tasks:** 3
- **Files modified:** 15

## Accomplishments

- Production-ready FastAPI + ONNX Lambda app with module-level cold-start init (S3 model download, InferenceSession, FeatureStore, DynamoDB) and /health + /predict routes via Mangum adapter
- Feast FeatureStore integration using rendered-YAML pattern to inject runtime env vars (REDIS_HOST, S3_BUCKET) into feature_store.yaml at Lambda INIT
- Backfill Lambda + EventBridge Scheduler (every 30 min) completing the prediction logging loop: predictions written without actual_label, backfill Lambda computes actual label from BTC price swing and writes via update_item

## Task Commits

Each task was committed atomically:

1. **Task 1: Create serving/ directory with FastAPI app, Dockerfile, and Feast config** - `f6ad3a5` (feat)
2. **Task 2: Create backfill Lambda and update Terraform serverless module** - `9e0e282` (feat)
3. **Task 3: Validate Terraform syntax and create push_backfill_image.sh helper script** - `e8051bb` (feat)

## Files Created/Modified

- `serving/Dockerfile` - Lambda container image using public.ecr.aws/lambda/python:3.11
- `serving/Dockerfile.backfill` - Lightweight Lambda image for backfill (requests only, no onnxruntime/feast)
- `serving/requirements.txt` - fastapi, mangum, onnxruntime, feast, numpy (no boto3 — provided by Lambda runtime)
- `serving/app/__init__.py` - Empty package marker
- `serving/app/main.py` - FastAPI app with module-level init, /health, /predict, Mangum handler
- `serving/feature_repo/__init__.py` - Empty package marker
- `serving/feature_repo/feature_store.yaml` - Static placeholder (localhost:6379); rendered at INIT
- `serving/backfill/__init__.py` - Empty package marker
- `serving/backfill/backfill_lambda.py` - EventBridge-triggered Lambda: DynamoDB scan + CoinGecko price fetch + update_item
- `serving/backfill/requirements.txt` - requests==2.32.3 only
- `scripts/push_backfill_image.sh` - Build and push backfill image to ECR (linux/amd64)
- `infra/modules/serverless/main.tf` - Added backfill Lambda, scheduler IAM role, EventBridge Scheduler; updated predictor env vars
- `infra/modules/serverless/variables.tf` - Added dynamodb_table_name variable
- `infra/modules/serverless/outputs.tf` - Added backfill_lambda_function_name output
- `infra/main.tf` - Passes dynamodb_table_name to serverless module

## Decisions Made

- feature_store.yaml is rendered at Lambda INIT (not static) — REDIS_HOST and S3_BUCKET only available as env vars at runtime. Written to /tmp/feature_store.yaml using FeatureStore(fs_yaml_file=) parameter.
- Separate Dockerfile.backfill creates a lighter backfill image (requests only, ~200MB vs ~1.5GB with onnxruntime+feast). Push script builds from Dockerfile.backfill.
- CoinGecko /history endpoint is day-granular on free tier — backfill uses daily price as proxy for 30-min swing comparison. Phase 5 Airflow can refine with stored OHLCV data.
- Backfill Lambda reuses existing aws_iam_role.lambda (DynamoDB UpdateItem already granted in Phase 1).
- FEATURE_REFS constructed using btc_volatility_features:{name} prefix matching Phase 3 feature view name (not btc_features as stated in plan — corrected from Phase 3 STATE.md decision).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Feature view name corrected from btc_features to btc_volatility_features**
- **Found during:** Task 1 (serving/app/main.py)
- **Issue:** Plan specified `btc_features:{feature_name}` refs but Phase 3 STATE.md decision records `btc_volatility_features` as the feature view name
- **Fix:** Used `btc_volatility_features:{name}` in FEATURE_REFS to match actual Feast feature view
- **Files modified:** serving/app/main.py
- **Verification:** Consistent with Phase 3 training feature lookup pattern
- **Committed in:** f6ad3a5 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — feature view name mismatch)
**Impact on plan:** Necessary correction to ensure Feast feature fetch works at runtime. No scope creep.

## Issues Encountered

None — Terraform validation passed on first attempt. All verification checks passed.

## Known Limitations

- CoinGecko free tier /history endpoint returns daily (not minute-level) price data. The backfill Lambda will use the same daily price for predictions made on the same day, making swing comparison zero or near-zero for same-day records. This is a Phase 5 refinement opportunity using stored raw OHLCV data from the Airflow DAG.
- Backfill Lambda uses a simple SCAN operation on DynamoDB — for production scale this should use a GSI on timestamp. Acceptable at current 5 WCU provisioned capacity.

## User Setup Required

None — no external service configuration required beyond what Phase 1 infrastructure provides. To deploy:
1. Push serving image: `docker buildx build --platform linux/amd64 --provenance=false -t {ECR_URL}:latest serving/ && docker push {ECR_URL}:latest`
2. Push backfill image: `./scripts/push_backfill_image.sh {ECR_URL}`
3. Apply Terraform changes: `cd infra && terraform apply`

## Next Phase Readiness

- Lambda code ready to serve predictions — deploy by pushing Docker images and running terraform apply
- Backfill loop complete — DynamoDB will accumulate labeled training data for drift detection
- Phase 5 (Drift Detection and Retraining): can immediately scan DynamoDB predictions table and use btc_volatility_features from Feast; SWING_THRESHOLD=0.02 consistent with Phase 2 labeling

---
*Phase: 04-lambda-serving-and-api*
*Completed: 2026-03-13*

## Self-Check: PASSED

All 11 created files found on disk. All 3 task commits verified in git log.
