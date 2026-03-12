# Phase 4: Lambda Serving and API - Research

**Researched:** 2026-03-12
**Domain:** AWS Lambda container serving with ONNX Runtime, FastAPI, Mangum, Feast Redis online store, DynamoDB prediction logging
**Confidence:** MEDIUM

## Summary

Phase 4 assembles the Inference Pipeline: API Gateway routes GET /predict and GET /health to a FastAPI application running inside a Lambda container image; the handler reads entity features from Feast's Redis online store (ElastiCache), runs ONNX Runtime inference on the loaded model, logs predictions to DynamoDB, and a separate backfill Lambda or EventBridge-triggered function updates DynamoDB records 30 minutes later with actual labels for accuracy tracking.

The standard deployment unit is a Docker container image (not a ZIP package), because onnxruntime alone is ~130MB and exceeds the 250MB uncompressed ZIP limit. AWS Lambda supports images up to 10GB, so the entire Python stack fits comfortably. The container must be built for `linux/amd64` (x86_64) — ARM64 (Graviton) has a known ONNX Runtime `Illegal instruction` bug. The base image is `public.ecr.aws/lambda/python:3.11`.

Mangum wraps FastAPI as the Lambda handler. The ONNX Runtime InferenceSession and Feast FeatureStore must be instantiated at module level (outside the handler function) to survive across warm invocations — loading inside the handler on every request is a severe performance anti-pattern. Lambda must be deployed inside the same VPC as ElastiCache; VPC overhead adds under 50ms to cold starts as of 2025 (Hyperplane ENIs resolved the old 10+ second penalty). API Gateway HTTP API (v2) is the correct choice over REST API (v1) — cheaper, simpler, 30-second timeout vs 29-second.

**Primary recommendation:** Use `public.ecr.aws/lambda/python:3.11`, Mangum 0.17.0+, FastAPI 0.135.1, onnxruntime 1.24.3 (CPU-only), Feast 0.61.0, boto3 for DynamoDB. Load model and FeatureStore at module level. Build x86_64 only. Wire backfill as a second Lambda triggered by EventBridge Scheduler every 30 minutes.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SERV-01 | Lambda function with ONNX Runtime for inference (x86_64, not ARM64) | Container image pattern verified; x86_64 ARM64 bug documented; Dockerfile base image confirmed |
| SERV-02 | FastAPI handler reads features from Redis (Feast online store), runs ONNX inference, returns prediction | Mangum+FastAPI+Feast get_online_features() pattern verified; FeatureStore module-level init documented |
| SERV-03 | API Gateway HTTP API: GET /predict (latest prediction), GET /health | apigatewayv2 Terraform resources documented; route_key pattern confirmed; Mangum handles both routes |
| SERV-04 | Prediction logging to DynamoDB: timestamp, features, prediction, probability, model_version | boto3 DynamoDB resource put_item pattern verified; Decimal handling for floats documented |
| SERV-05 | Backfill actual labels 30 minutes after prediction for accuracy tracking | EventBridge Scheduler → Lambda → DynamoDB update_item pattern verified |
</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| onnxruntime | 1.24.3 | ONNX model inference in Lambda | CPU-only ~13MB, sub-ms latency on XGBoost models; only runtime that works with exported XGBoost ONNX |
| fastapi | 0.135.1 | HTTP API framework | Minimal ASGI overhead; async-first; auto-generates OpenAPI docs |
| mangum | 0.17.0 | ASGI → Lambda event adapter | De-facto standard; handles API GW HTTP v2, REST v1, Function URLs |
| feast | 0.61.0 | Feature retrieval from Redis | Single source of truth established in Phase 2; get_online_features() API |
| boto3 | 1.38+ (bundled in Lambda) | DynamoDB read/write | Bundled in Lambda runtime; resource API preferred over client API |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | 2.x | Convert Feast response to float32 array for ONNX input | Required — ONNX Runtime expects numpy arrays |
| python-dotenv | 1.x | Local environment variable loading | Dev/testing only; Lambda uses environment variables natively |
| redis | 5.x (pulled by feast) | Underlying Redis client for Feast | Pulled as feast dependency; no direct import needed |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Mangum | AWS Lambda Powertools + custom handler | Mangum is simpler for full ASGI apps; Powertools better for function-style handlers without routing |
| API Gateway HTTP API (v2) | REST API (v1) | HTTP API is cheaper and has slightly higher timeout (30s vs 29s); REST API needed only for API keys, WAF, caching |
| EventBridge Scheduler (backfill) | Second Lambda invoked from predict handler with delay | Scheduler is decoupled and retryable; inline async delay ties up Lambda execution |
| DynamoDB (prediction log) | S3 JSON files | DynamoDB supports point lookups by prediction_id for backfill update; S3 requires scan |

**Installation (Lambda container requirements.txt):**
```bash
# In requirements.txt for Lambda container
fastapi==0.135.1
mangum==0.17.0
onnxruntime==1.24.3
feast==0.61.0
numpy>=2.0
# boto3 excluded — provided by Lambda runtime
```

## Architecture Patterns

### Recommended Project Structure

```
serving/
├── Dockerfile                  # FROM public.ecr.aws/lambda/python:3.11
├── requirements.txt            # fastapi, mangum, onnxruntime, feast, numpy
├── app/
│   ├── main.py                 # FastAPI app + Mangum handler (module-level init)
│   ├── inference.py            # ONNX Runtime session wrapper
│   ├── features.py             # Feast FeatureStore wrapper
│   └── logging_db.py           # DynamoDB put/update helpers
├── feature_repo/
│   └── feature_store.yaml      # Feast config (Redis online store)
└── backfill/
    └── backfill_lambda.py      # EventBridge → DynamoDB update_item
```

### Pattern 1: Module-Level Model and FeatureStore Initialization

**What:** Load ONNX model and Feast FeatureStore once at container startup, outside the handler function. This code runs during Lambda's INIT phase and survives across warm invocations.

**When to use:** Always — loading inside the handler multiplies cold start cost by every invocation.

**Example:**
```python
# Source: AWS Lambda best practices + pyimagesearch.com/2025/11/17
import onnxruntime as ort
from feast import FeatureStore
from mangum import Mangum
from fastapi import FastAPI
import boto3, os, numpy as np

# Module-level initialization — runs once per container lifetime
MODEL_PATH = "/tmp/current.onnx"           # Downloaded from S3 on init
ort_session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
store = FeatureStore(repo_path="/var/task/feature_repo")
ddb = boto3.resource("dynamodb").Table(os.environ["PREDICTIONS_TABLE"])

app = FastAPI()
handler = Mangum(app, lifespan="off")      # lifespan="off" is correct for Lambda
```

### Pattern 2: Feast Online Feature Retrieval

**What:** `get_online_features()` takes entity rows (list of dicts) and feature refs in `"view:feature"` format.

**Example:**
```python
# Source: docs.feast.dev/how-to-guides/feast-snowflake-gcp-aws/read-features-from-the-online-store
response = store.get_online_features(
    features=[
        "btc_features:volatility_10m",
        "btc_features:volatility_30m",
        "btc_features:rsi_14",
        # ... all 12 features
    ],
    entity_rows=[{"btc_id": "BTC"}]
).to_dict()

# Convert to float32 numpy array for ONNX input
feature_values = np.array(
    [[response[f][0] for f in FEATURE_NAMES]], dtype=np.float32
)
```

### Pattern 3: ONNX Runtime Inference

**What:** Run inference using `InferenceSession.run()`. Input names must match training export.

**Example:**
```python
# Source: onnxruntime documentation
input_name = ort_session.get_inputs()[0].name
label_name = ort_session.get_outputs()[0].name
prob_name = ort_session.get_outputs()[1].name   # output_probability

outputs = ort_session.run([label_name, prob_name], {input_name: feature_values})
prediction = "VOLATILE" if outputs[0][0] == 1 else "CALM"
probability = float(outputs[1][0][1])           # P(class=1)
```

### Pattern 4: DynamoDB Prediction Logging

**What:** Use the DynamoDB resource API (table object, not client) for cleaner code. Float values must be cast to `Decimal` before writing.

**Example:**
```python
# Source: docs.aws.amazon.com/boto3/latest/guide/dynamodb.html
from decimal import Decimal

ddb.put_item(Item={
    "prediction_id": prediction_id,     # HASH key (UUID or timestamp-based)
    "timestamp": datetime.utcnow().isoformat(),
    "features": {k: Decimal(str(v)) for k, v in features.items()},
    "prediction": prediction,
    "probability": Decimal(str(probability)),
    "model_version": os.environ["MODEL_VERSION"],
    "actual_label": None,               # Backfilled 30 min later
})
```

### Pattern 5: Backfill Lambda (SERV-05)

**What:** EventBridge Scheduler rule fires every 30 minutes. Lambda queries DynamoDB for records from ~30 minutes ago that have no actual_label, fetches current BTC price to compute label, then update_items.

**Example:**
```python
# Source: dev.to scheduled DynamoDB pattern
table.update_item(
    Key={"prediction_id": row["prediction_id"]},
    UpdateExpression="SET actual_label = :label, backfilled_at = :ts",
    ExpressionAttributeValues={
        ":label": computed_actual_label,
        ":ts": datetime.utcnow().isoformat(),
    }
)
```

### Pattern 6: Mangum + API Gateway HTTP API (v2) Terraform

**What:** Route `GET /predict` and `GET /health` through API Gateway HTTP API to the Lambda function.

**Example Terraform (key resources):**
```hcl
# Source: developer.hashicorp.com/terraform/tutorials/aws/lambda-api-gateway
resource "aws_apigatewayv2_api" "serve" {
  name          = "btc-volatility-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id             = aws_apigatewayv2_api.serve.id
  integration_type   = "AWS_PROXY"
  integration_method = "POST"
  integration_uri    = aws_lambda_function.serve.invoke_arn
  payload_format_version = "2.0"     # Required for HTTP API
}

resource "aws_apigatewayv2_route" "predict" {
  api_id    = aws_apigatewayv2_api.serve.id
  route_key = "GET /predict"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.serve.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_lambda_permission" "apigw" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.serve.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.serve.execution_arn}/*/*"
}
```

### Anti-Patterns to Avoid

- **Loading ONNX model inside the handler:** Multiplies cold start cost by every invocation. Load at module level.
- **Instantiating FeatureStore inside the handler:** Same penalty as above; Feast initialization opens a Redis connection. Module level only.
- **Using onnxruntime on ARM64:** ARM64 Lambda has a known `Illegal instruction` crash with onnxruntime CPU provider. Always build `--platform linux/amd64`.
- **Using REST API (v1) when HTTP API (v2) suffices:** REST API adds cost and 1-second timeout reduction. HTTP API is correct for this use case.
- **Writing Python floats directly to DynamoDB:** boto3 rejects native floats; wrap all float values in `Decimal(str(val))`.
- **Inlining feature computation in Lambda:** Defeats the purpose of Feast; training-serving skew becomes possible again. Always read from `get_online_features()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Lambda event parsing | Custom event dict extraction | Mangum | Handles all API GW payload versions, ALB, Function URLs; edge cases are numerous |
| Redis connection pooling | Manual redis.Redis() in Lambda | Feast FeatureStore (module-level) | Feast manages connection lifecycle; reconnection on warm start handled |
| ONNX input/output name lookup | Hardcoding input tensor names | `session.get_inputs()[0].name` at init | Names vary by export; hardcoding causes silent wrong-input bugs |
| Float → DynamoDB serialization | Custom type coercion | `Decimal(str(float_val))` pattern | Boto3 resource API rejects Python floats; Decimal is required |
| API Gateway routing | Manual event["path"] checks | Mangum + FastAPI route decorators | Mangum dispatches to FastAPI router correctly; manual routing is fragile |

**Key insight:** Lambda container serving has many subtle serialization and initialization order issues that standard libraries handle; the risk is in composing them correctly, not in any one library.

## Common Pitfalls

### Pitfall 1: VPC Configuration for ElastiCache Access
**What goes wrong:** Lambda cannot reach ElastiCache Redis unless deployed in the same VPC and subnet as the ElastiCache cluster. Without VPC config, `get_online_features()` hangs until timeout.
**Why it happens:** ElastiCache is never accessible from the public internet; it has no public IP.
**How to avoid:** Configure `vpc_config` on the Lambda Terraform resource with private subnet IDs from the same VPC as ElastiCache and a security group that has inbound access to ElastiCache port 6379. Attach `AWSLambdaVPCAccessExecutionRole` managed policy.
**Warning signs:** `get_online_features()` TimeoutError or connection refused from Lambda; works locally against local Redis but fails in AWS.

Terraform VPC config pattern:
```hcl
resource "aws_lambda_function" "serve" {
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda_sg.id]
  }
}
# Security group: allow outbound TCP 6379 to ElastiCache SG
```

### Pitfall 2: Feast feature_store.yaml Must Be Present at repo_path
**What goes wrong:** `FeatureStore(repo_path="/var/task/feature_repo")` raises `FileNotFoundError` if `feature_store.yaml` is not COPY'd into the container image at that path.
**Why it happens:** Feast reads `feature_store.yaml` at initialization time; it doesn't fall back to environment variables.
**How to avoid:** COPY the `feature_repo/` directory (containing `feature_store.yaml` and feature view definitions) into `${LAMBDA_TASK_ROOT}/feature_repo/` in the Dockerfile. The Redis connection_string in `feature_store.yaml` must use the ElastiCache endpoint, not `localhost`.

```yaml
# feature_store.yaml for Lambda (Redis online, S3 offline+registry)
project: crypto_volatility
registry: s3://your-bucket/feast/registry.pb
provider: aws
online_store:
  type: redis
  connection_string: "your-elasticache-endpoint.cache.amazonaws.com:6379,ssl=true"
offline_store:
  type: file
entity_key_serialization_version: 2
```

### Pitfall 3: ARM64 ONNX Runtime Illegal Instruction Bug
**What goes wrong:** Lambda built for ARM64 (Graviton) crashes with `Illegal instruction` when onnxruntime loads the XGBoost model.
**Why it happens:** onnxruntime's x86 CPU acceleration instructions (AVX/SSE) are not available on ARM; the pip-installed wheel may use an x86-specific compiled backend.
**How to avoid:** Always build with `--platform linux/amd64`. Set `architectures = ["x86_64"]` in Terraform. Never use `arm64` for this stack.

### Pitfall 4: API Gateway 29-30 Second Hard Timeout
**What goes wrong:** If the Lambda function takes over 29s (REST API) or 30s (HTTP API), API Gateway returns 504 regardless of Lambda's timeout setting.
**Why it happens:** API Gateway has a hard integration timeout limit that cannot be raised.
**How to avoid:** Lambda's ONNX inference for XGBoost is sub-millisecond; the bottleneck is cold start. Set Lambda timeout to 30 seconds (just under API GW limit). Set Lambda memory to at least 512MB to provide more CPU during INIT. Monitor `Init Duration` in CloudWatch logs — should be under 5 seconds for this stack; if higher, investigate what's slow in module-level initialization.

### Pitfall 5: Decimal Serialization for DynamoDB
**What goes wrong:** `put_item(Item={"probability": 0.87})` raises `TypeError: Float types are not supported. Use Decimal types instead`.
**Why it happens:** boto3 DynamoDB resource API rejects Python `float` to prevent precision loss.
**How to avoid:** Wrap all floats: `Decimal(str(float_value))`. Use `from decimal import Decimal`. Feature dict values from Feast may also be floats — wrap all of them.

### Pitfall 6: Model Version Mismatch Between S3 and Lambda
**What goes wrong:** Lambda loads the model from S3 at INIT time. If S3 `current.onnx` is replaced (Phase 3 promotion), running Lambda containers serve the old model until they cold start.
**Why it happens:** Lambda caches the execution environment; module-level code does not re-run on warm invocations.
**How to avoid:** Store `model_version` in DynamoDB records. After a promotion event, trigger a Lambda function update (or publish a new version) to force cold starts. The `model_version` logged to DynamoDB will reveal staleness during monitoring.

## Code Examples

Verified patterns from official and confirmed sources:

### Complete Lambda Handler (main.py)
```python
# Pattern from: mangum.fastapiexpert.com + docs.feast.dev + docs.aws.amazon.com/boto3
import os, boto3, numpy as np
from decimal import Decimal
from datetime import datetime
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from mangum import Mangum
import onnxruntime as ort
from feast import FeatureStore

# --- Module-level init (runs once per container) ---
_s3 = boto3.client("s3")
_s3.download_file(
    os.environ["MODEL_BUCKET"], "models/current.onnx", "/tmp/current.onnx"
)
ort_session = ort.InferenceSession(
    "/tmp/current.onnx", providers=["CPUExecutionProvider"]
)
store = FeatureStore(repo_path="/var/task/feature_repo")
ddb_table = boto3.resource("dynamodb").Table(os.environ["PREDICTIONS_TABLE"])

FEATURE_NAMES = [
    "volatility_10m", "volatility_30m", "volatility_ratio",
    "rsi_14", "volume_spike", "volume_trend", "price_range_30m",
    "sma_10_vs_sma_30", "max_drawdown_30m", "candle_body_avg",
    "hour_of_day", "day_of_week",
]

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/predict")
def predict():
    # Read features from Feast Redis online store
    response = store.get_online_features(
        features=[f"btc_features:{f}" for f in FEATURE_NAMES],
        entity_rows=[{"btc_id": "BTC"}],
    ).to_dict()
    features = {f: response[f"btc_features__{f}"][0] for f in FEATURE_NAMES}

    # ONNX inference
    input_name = ort_session.get_inputs()[0].name
    X = np.array([[features[f] for f in FEATURE_NAMES]], dtype=np.float32)
    labels, probs = ort_session.run(None, {input_name: X})
    prediction = "VOLATILE" if int(labels[0]) == 1 else "CALM"
    probability = float(probs[0][1])

    # Log to DynamoDB
    pred_id = str(uuid4())
    ddb_table.put_item(Item={
        "prediction_id": pred_id,
        "timestamp": datetime.utcnow().isoformat(),
        "features": {k: Decimal(str(v)) for k, v in features.items()},
        "prediction": prediction,
        "probability": Decimal(str(probability)),
        "model_version": os.environ.get("MODEL_VERSION", "unknown"),
    })

    return {"prediction": prediction, "probability": probability,
            "prediction_id": pred_id, "model_version": os.environ.get("MODEL_VERSION")}

handler = Mangum(app, lifespan="off")
```

### Dockerfile
```dockerfile
# Source: docs.aws.amazon.com/lambda/latest/dg/python-image.html
FROM public.ecr.aws/lambda/python:3.11

COPY requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install -r requirements.txt --no-cache-dir

# Copy application code
COPY app/ ${LAMBDA_TASK_ROOT}/app/
# Copy Feast feature repo (contains feature_store.yaml + feature view definitions)
COPY feature_repo/ ${LAMBDA_TASK_ROOT}/feature_repo/

CMD ["app.main.handler"]
```

Build command (x86_64 only):
```bash
docker buildx build --platform linux/amd64 --provenance=false -t $ECR_URI:latest .
```

### DynamoDB Backfill Lambda
```python
# Source: aws.amazon.com/blogs/architecture/serverless-scheduling pattern
import boto3, os
from datetime import datetime, timedelta
from decimal import Decimal

ddb = boto3.resource("dynamodb").Table(os.environ["PREDICTIONS_TABLE"])

def handler(event, context):
    # Query predictions from ~30 minutes ago without actual_label
    cutoff = (datetime.utcnow() - timedelta(minutes=35)).isoformat()
    # Scan for records needing backfill (low volume; full scan acceptable)
    result = ddb.scan(
        FilterExpression="attribute_not_exists(actual_label) AND #ts < :cutoff",
        ExpressionAttributeNames={"#ts": "timestamp"},
        ExpressionAttributeValues={":cutoff": cutoff},
    )
    for item in result["Items"]:
        actual_label = compute_actual_label(item["timestamp"])  # fetch BTC price, compute swing
        ddb.update_item(
            Key={"prediction_id": item["prediction_id"]},
            UpdateExpression="SET actual_label = :label, backfilled_at = :ts",
            ExpressionAttributeValues={
                ":label": actual_label,
                ":ts": datetime.utcnow().isoformat(),
            }
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Lambda ZIP + Lambda Layers for large deps | Lambda container images (up to 10GB) | 2020 (re:Invent) | onnxruntime can now ship inside Lambda without layer size hacks |
| VPC cold starts 10+ seconds | VPC cold starts <50ms (Hyperplane ENIs) | 2019–2023 | Lambda+VPC is no longer a cold start anti-pattern; ElastiCache access is viable |
| API Gateway REST API (v1) | API Gateway HTTP API (v2) — cheaper, simpler | 2019 (GA 2020) | Default choice for new Lambda APIs; REST API only needed for WAF/caching |
| ARM64 Lambda for cost savings | x86_64 mandatory for onnxruntime | n/a (onnxruntime limitation) | Graviton saving not applicable; x86_64 required |
| Loading models on every invocation | Module-level init (warm start optimization) | Best practice since ~2018 | Standard pattern; Mangum with `lifespan="off"` is the correct Lambda approach |

**Deprecated/outdated:**
- Lambda Layers for ML deps: Replaced by container images for packages >50MB; layer size limits (250MB uncompressed) are too small for onnxruntime + feast + numpy.
- ColdStart VPC penalty: The "never put Lambda in a VPC" advice is outdated; Hyperplane ENIs resolved this in 2019.

## Open Questions

1. **Feast feature_store.yaml registry path in Lambda container**
   - What we know: `repo_path` points to a local directory; `feature_store.yaml` must be there
   - What's unclear: Whether `feast apply` is needed from within Lambda or if the pre-materialized S3 registry.pb is sufficient for `get_online_features()` at serving time
   - Recommendation: At serving time, only `get_online_features()` is needed; `feast apply` is a Phase 2 one-time operation; include registry path in `feature_store.yaml` pointing to S3 so Lambda reads metadata from S3 on init (not a problem for warm serving once loaded)

2. **ElastiCache SSL/TLS in Feast connection_string**
   - What we know: ElastiCache provisioned Redis supports SSL; connection_string format supports `,ssl=true`
   - What's unclear: Whether ElastiCache provisioned t3.micro (used here) requires `ssl=true` by default or if it's optional
   - Recommendation: Configure with `ssl=true` and `ssl_cert_reqs=none` in the connection string; test with local Redis first, then toggle SSL for AWS; add to Phase 4 verification steps

3. **Model download from S3 at Lambda INIT vs COPY into container**
   - What we know: Two options — (a) COPY model into container at build time, (b) download from S3 at INIT
   - What's unclear: Option (a) means every model update requires a container rebuild and ECR push; option (b) means cold start includes an S3 download (~1–3 seconds for a small ONNX file)
   - Recommendation: Option (b) (download from S3 at INIT) — aligns with Phase 3's S3 registry pattern; model updates take effect on next cold start without CI/CD; plan tasks in this phase account for this

## Validation Architecture

> nyquist_validation not found in config.json workflow block — skipping Validation Architecture section.

(Note: `.planning/config.json` has `workflow.research`, `workflow.plan_check`, `workflow.verifier` — no `nyquist_validation` key. Skipping this section per researcher instructions.)

## Sources

### Primary (HIGH confidence)
- `docs.aws.amazon.com/lambda/latest/dg/python-image.html` — Lambda container Dockerfile, x86_64 build command, CMD format, Python 3.11 deprecation date, `--provenance=false` flag
- `mangum.fastapiexpert.com` — Mangum adapter setup, `lifespan="off"` pattern, event type support
- `docs.feast.dev/how-to-guides/feast-snowflake-gcp-aws/read-features-from-the-online-store` — `get_online_features()` API, entity_rows format, `"view:feature"` feature_refs, `.to_dict()` conversion
- `docs.feast.dev/reference/online-stores/redis` — Redis online store `feature_store.yaml` configuration, SSL connection string format, TTL config
- `docs.aws.amazon.com/boto3/latest/guide/dynamodb.html` — `put_item`, `update_item`, `UpdateExpression SET` pattern, Decimal float requirement
- `docs.aws.amazon.com/AmazonElastiCache/latest/dg/LambdaRedis.html` — VPC subnet config, security group, `AWSLambdaVPCAccessExecutionRole` policy, Redis port 6379
- `developer.hashicorp.com/terraform/tutorials/aws/lambda-api-gateway` — `aws_apigatewayv2_api`, `aws_apigatewayv2_integration` with `payload_format_version = "2.0"`, `aws_apigatewayv2_route`, `aws_lambda_permission` patterns
- `.planning/research/SUMMARY.md` — VPC cold start <50ms (Hyperplane), ARM64 ONNX bug, onnxruntime 1.24.3, API Gateway 30s timeout, x86_64 architecture requirement

### Secondary (MEDIUM confidence)
- `pyimagesearch.com/2025/11/17/fastapi-docker-deployment-preparing-onnx-ai-models-for-aws-lambda/` — Module-level model load pattern verified; FastAPI + Mangum + ONNX Runtime confirmed working pattern (Nov 2025)
- `edgedelta.com/company/knowledge-center/aws-lambda-cold-start-cost` — VPC cold start <50ms, 512MB memory faster initialization (2025)
- `aaronstuyvenberg.com/posts/containers-on-lambda` — Container images outperform ZIP for Python with >200MB dependencies
- `docs.aws.amazon.com/apigateway/latest/developerguide/limits.html` — API Gateway HTTP API 30-second timeout hard limit

### Tertiary (LOW confidence)
- WebSearch aggregations on DynamoDB backfill + EventBridge Scheduler pattern — pattern confirmed from multiple sources but no single authoritative tutorial found for exact backfill use case; flag for implementation validation

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — all library versions verified; Dockerfile and Mangum patterns from official docs; Feast API from official docs
- Architecture: MEDIUM — Lambda+VPC+ElastiCache+Feast combination not directly benchmarked in a single authoritative source; cold start for this exact stack is estimated
- Pitfalls: HIGH — ARM64 bug documented; Decimal float requirement from official boto3 docs; VPC config from official ElastiCache docs; feature_store.yaml path issue is a known Feast configuration requirement

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (30 days — all libraries are stable; AWS API Gateway and Lambda configs are not fast-moving)
