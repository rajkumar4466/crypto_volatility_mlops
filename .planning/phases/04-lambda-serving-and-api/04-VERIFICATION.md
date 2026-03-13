---
phase: 04-lambda-serving-and-api
verified: 2026-03-13T16:00:00Z
status: gaps_found
score: 6/7 must-haves verified
re_verification: false
gaps:
  - truth: "Backfill Lambda reads DynamoDB items ~30 min old with no actual_label, computes actual VOLATILE/CALM label from BTC price swing, and writes actual_label + backfilled_at via update_item"
    status: failed
    reason: "backfill_lambda.py passes a raw string to FilterExpression in table.scan(), but boto3.resource DynamoDB Table requires a Boto3 Condition expression object (Attr/Key), not a raw string. The low-level string syntax is only valid for boto3.client. This will raise ParamValidationError at runtime and the scan will never find or process any items."
    artifacts:
      - path: "serving/backfill/backfill_lambda.py"
        issue: "FilterExpression is a raw string 'attribute_not_exists(actual_label) AND #ts BETWEEN :start AND :end' — must be Attr('actual_label').not_exists() & Attr('timestamp').between(cutoff_start, cutoff_end) using boto3.dynamodb.conditions.Attr"
    missing:
      - "Import Attr from boto3.dynamodb.conditions at top of backfill_lambda.py"
      - "Replace raw string FilterExpression with: Attr('actual_label').not_exists() & Attr('timestamp').between(cutoff_start, cutoff_end)"
      - "Remove ExpressionAttributeNames (not needed when using Attr builder) and ExpressionAttributeValues (Attr builder handles value substitution automatically)"
human_verification:
  - test: "Deploy Lambda container image and hit GET /predict"
    expected: "Returns JSON with prediction (VOLATILE or CALM), probability float, prediction_id UUID, model_version string"
    why_human: "Requires live Redis with Feast-materialized features and S3 ONNX model — cannot verify end-to-end without deployed infrastructure"
  - test: "Check DynamoDB after GET /predict"
    expected: "New item present with all required fields: prediction_id, timestamp, features map (12 keys), prediction, probability as Decimal, model_version, ttl; no actual_label attribute"
    why_human: "Requires live DynamoDB table and deployed Lambda"
  - test: "Wait 30+ minutes after /predict call, check DynamoDB item"
    expected: "Item now has actual_label (VOLATILE, CALM, or UNKNOWN) and backfilled_at timestamp set by backfill Lambda"
    why_human: "Requires EventBridge Scheduler trigger and live backfill Lambda — but also depends on fixing the FilterExpression bug above before this will work"
---

# Phase 4: Lambda Serving and API Verification Report

**Phase Goal:** A live API endpoint returns BTC volatility predictions by reading features from Redis and running ONNX inference, with predictions logged for accuracy tracking
**Verified:** 2026-03-13T16:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | GET /health returns HTTP 200 from the API Gateway URL | ? HUMAN | /health route defined at line 92-95 of main.py, Mangum handler wired, API Gateway routes provisioned in Terraform — live test needed |
| 2  | GET /predict returns JSON with prediction, probability, model_version, prediction_id — features from Feast Redis, no inline feature computation | ? HUMAN | Route defined lines 98-159, get_online_features called with entity_rows=[{"btc_id": "BTC"}], ort_session.run wired, returns correct keys — live test needed |
| 3  | Each /predict response causes a new DynamoDB item with all required fields | ? HUMAN | ddb_table.put_item wired at line 139 with all required fields; live test needed |
| 4  | DynamoDB items written by /predict have no actual_label attribute at creation time | VERIFIED | put_item Item dict (lines 140-149) contains no actual_label key — omission is intentional and confirmed in code |
| 5  | Backfill Lambda reads DynamoDB items ~30 min old with no actual_label, computes actual label, writes actual_label + backfilled_at via update_item | FAILED | FilterExpression passed as raw string to boto3.resource Table.scan() — this is invalid; boto3 resource API requires Attr/Key condition objects. update_item logic is correct but is unreachable due to the scan bug. |
| 6  | Lambda container image is built for linux/amd64 (x86_64), NOT arm64 | VERIFIED | Dockerfile uses public.ecr.aws/lambda/python:3.11 (no platform flag — relies on push script); push_backfill_image.sh specifies --platform linux/amd64 --provenance=false; both Lambda functions set architectures = ["x86_64"] in Terraform; no arm64 references in code |
| 7  | ONNX model and Feast FeatureStore are initialized at module level (outside handler function) | VERIFIED | Lines 45-80 of main.py: S3 download, InferenceSession, FeatureStore, DynamoDB table all initialized at module level before FastAPI app definition |

**Score:** 4/7 truths fully verified (2 human-needed, 1 failed)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `serving/Dockerfile` | Lambda container image using public.ecr.aws/lambda/python:3.11 | VERIFIED | Line 1: `FROM public.ecr.aws/lambda/python:3.11`, CMD ["app.main.handler"] |
| `serving/requirements.txt` | Python dependencies including onnxruntime | VERIFIED | fastapi==0.135.1, mangum==0.17.0, onnxruntime==1.24.3, feast==0.61.0, numpy>=2.0,<3.0, requests==2.32.3 — no boto3 (correct) |
| `serving/app/main.py` | FastAPI app with /health and /predict routes + Mangum handler, exports app and handler | VERIFIED | Both routes present, handler = Mangum(app, lifespan="off") at line 166, module-level init complete |
| `serving/feature_repo/feature_store.yaml` | Feast configuration with redis online_store type | VERIFIED | online_store.type: redis present; static placeholder values (localhost:6379) as intended — rendered at Lambda INIT via main.py |
| `serving/backfill/backfill_lambda.py` | EventBridge-triggered Lambda that backfills actual_label into DynamoDB, exports handler | STUB/WIRING BUG | File exists, handler function defined, update_item logic correct — but FilterExpression bug prevents scan from working at runtime |
| `infra/modules/serverless/main.tf` | Updated Terraform with backfill Lambda + EventBridge Scheduler | VERIFIED | aws_lambda_function.backfill at line 145, aws_scheduler_schedule.backfill at line 197 with rate(30 minutes) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| serving/app/main.py | Feast Redis online store | FeatureStore.get_online_features() | VERIFIED | Line 107: store.get_online_features(features=FEATURE_REFS, entity_rows=[{"btc_id": "BTC"}]) |
| serving/app/main.py | ONNX Runtime InferenceSession | ort_session.run() | VERIFIED | Line 125: outputs = ort_session.run(_output_names, {_input_name: X}), both label and probability extracted |
| serving/app/main.py | DynamoDB predictions table | ddb_table.put_item() | VERIFIED | Line 139-149: put_item with all required fields including Decimal(str()) conversions |
| serving/backfill/backfill_lambda.py | DynamoDB predictions table | table.update_item() with SET actual_label | PARTIAL | update_item at line 83 is correct; however the preceding table.scan() with raw string FilterExpression will raise ParamValidationError before update_item is reached |
| infra/modules/serverless/main.tf | EventBridge Scheduler | aws_scheduler_schedule resource, rate(30 minutes) | VERIFIED | aws_scheduler_schedule.backfill at line 197, schedule_expression = "rate(30 minutes)", target is backfill Lambda ARN |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SERV-01 | 04-01-PLAN.md | Lambda function with ONNX Runtime, x86_64 not ARM64 | SATISFIED | Dockerfile uses lambda/python:3.11 base, onnxruntime==1.24.3 in requirements.txt, Terraform architectures=["x86_64"] |
| SERV-02 | 04-01-PLAN.md | FastAPI handler reads features from Redis (Feast), runs ONNX inference, returns prediction | SATISFIED (pending live test) | get_online_features + ort_session.run both present and wired in /predict route |
| SERV-03 | 04-01-PLAN.md | API Gateway HTTP API: GET /predict and GET /health | SATISFIED | Both routes defined in main.py, Mangum handler wraps app, API Gateway routes provisioned in Terraform |
| SERV-04 | 04-01-PLAN.md | Prediction logging to DynamoDB: timestamp, features, prediction, probability, model_version | SATISFIED (pending live test) | put_item with all required fields including Decimal types for probability and feature values |
| SERV-05 | 04-01-PLAN.md | Backfill actual labels 30 min after prediction for accuracy tracking | BLOCKED | Backfill Lambda logic is implemented but will fail at runtime due to FilterExpression bug in table.scan() |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| serving/backfill/backfill_lambda.py | 69-71 | Raw string passed as FilterExpression to boto3.resource Table.scan() | BLOCKER | boto3 DynamoDB resource API requires Attr/Key condition objects — raw string is only valid for boto3.client (low-level). At runtime this will raise ParamValidationError and no items will ever be scanned or backfilled. SERV-05 is blocked. |

### Human Verification Required

#### 1. Live /predict Endpoint Test

**Test:** Deploy Lambda image, hit GET {api_gateway_url}/predict
**Expected:** HTTP 200 with JSON body containing prediction ("VOLATILE" or "CALM"), probability (float 0-1), prediction_id (UUID string), model_version string
**Why human:** Requires live Redis with Feast-materialized BTC features, S3 bucket with models/current.onnx, and deployed Lambda container

#### 2. DynamoDB Item Verification

**Test:** After calling GET /predict, scan DynamoDB predictions table
**Expected:** One new item with prediction_id (UUID), timestamp (ISO8601), features (map with 12 decimal keys), prediction (string), probability (Decimal), model_version (string), ttl (epoch int) — and NO actual_label attribute
**Why human:** Requires live DynamoDB table and deployed Lambda

#### 3. Backfill Loop Verification (after bug fix)

**Test:** After fixing FilterExpression bug and redeploying, wait 30+ minutes after a /predict call, then check the DynamoDB item
**Expected:** Item now has actual_label (VOLATILE, CALM, or UNKNOWN) and backfilled_at timestamp
**Why human:** Requires EventBridge Scheduler to fire, live CoinGecko API call to succeed, and the scan to correctly identify the item window

### Gaps Summary

One blocker gap prevents full goal achievement:

**SERV-05 Backfill — FilterExpression API mismatch:**
`serving/backfill/backfill_lambda.py` passes a raw ConditionExpression string to `table.scan()` from `boto3.resource("dynamodb")`. The high-level resource API does not accept raw strings — it requires `boto3.dynamodb.conditions.Attr` objects. The correct replacement is:

```python
from boto3.dynamodb.conditions import Attr

result = table.scan(
    FilterExpression=(
        Attr("actual_label").not_exists()
        & Attr("timestamp").between(cutoff_start, cutoff_end)
    ),
    ProjectionExpression="prediction_id, #ts",
    ExpressionAttributeNames={"#ts": "timestamp"},
)
```

Note: When using `Attr().between()` the `ExpressionAttributeValues` dict is handled automatically by the Attr builder and should be removed. The `ExpressionAttributeNames` for reserved word `timestamp` is still needed.

All other artifacts are substantive and correctly wired. The predictor Lambda (main.py) is fully correct. Terraform validates clean. The gap is isolated to a single method call in backfill_lambda.py.

---

_Verified: 2026-03-13T16:00:00Z_
_Verifier: Claude (gsd-verifier)_
