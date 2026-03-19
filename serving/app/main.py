"""FastAPI + ONNX Runtime Lambda handler for crypto volatility predictions.

Module-level initialization (cold-start once):
  - Downloads ONNX model from S3 to /tmp/current.onnx
  - Initializes ONNX Runtime InferenceSession
  - Renders feature_store.yaml with runtime env vars and initializes Feast FeatureStore
  - Connects to DynamoDB predictions table

Routes:
  GET /health  — liveness check
  GET /predict — fetch features from Feast Redis, run inference, log to DynamoDB
"""

import os
import time
import yaml
import boto3
import onnxruntime as ort
import numpy as np
from decimal import Decimal
from uuid import uuid4
from datetime import datetime, timedelta
from feast import FeatureStore
from fastapi import FastAPI, HTTPException
from mangum import Mangum

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEATURE_NAMES = [
    "volatility_10m", "volatility_30m", "volatility_ratio",
    "rsi_14", "volume_spike", "volume_trend", "price_range_30m",
    "sma_10_vs_sma_30", "max_drawdown_30m", "candle_body_avg",
    "hour_of_day", "day_of_week",
    "fear_greed", "market_cap_change_24h", "btc_dominance",
]

FEATURE_REFS = [f"btc_volatility_features:{name}" for name in FEATURE_NAMES]

# ---------------------------------------------------------------------------
# Module-level initialization (runs once per cold start)
# ---------------------------------------------------------------------------

# -- S3 model download -------------------------------------------------------
_s3 = boto3.client("s3")
_s3.download_file(
    os.environ["S3_BUCKET"],
    "models/current.onnx",
    "/tmp/current.onnx",
)

# -- ONNX Runtime InferenceSession -------------------------------------------
ort_session = ort.InferenceSession(
    "/tmp/current.onnx",
    providers=["CPUExecutionProvider"],
)
_input_name = ort_session.get_inputs()[0].name
# Outputs: [label (int64), probabilities (float32)]
_output_names = [o.name for o in ort_session.get_outputs()]

# -- Feast FeatureStore (rendered YAML to /tmp to resolve env vars at init) --
_rendered_yaml = {
    "project": "crypto_volatility",
    "registry": f"s3://{os.environ['S3_BUCKET']}/feast/registry.pb",
    "provider": "aws",
    "online_store": {
        "type": "redis",
        "connection_string": f"{os.environ['REDIS_HOST']}:6379",
    },
    "offline_store": {"type": "file"},
    "entity_key_serialization_version": 3,
}
with open("/tmp/feature_store.yaml", "w") as _f:
    yaml.dump(_rendered_yaml, _f)

store = FeatureStore(fs_yaml_file="/tmp/feature_store.yaml")

# -- DynamoDB table ----------------------------------------------------------
_ddb = boto3.resource("dynamodb")
ddb_table = _ddb.Table(os.environ["PREDICTIONS_TABLE"])

# -- Model version from env --------------------------------------------------
model_version = os.environ.get("MODEL_VERSION", "0.0.0")

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="Crypto Volatility Predictor", version=model_version)


@app.get("/health")
def health():
    """Liveness probe — returns status and model version."""
    return {"status": "ok", "model_version": model_version}


@app.get("/predict")
def predict():
    """Fetch features from Feast Redis, run ONNX inference, log to DynamoDB.

    Returns:
        JSON with prediction (VOLATILE|CALM), probability, prediction_id, model_version.
    """
    # 1. Fetch online features from Feast Redis
    try:
        feature_vector = store.get_online_features(
            features=FEATURE_REFS,
            entity_rows=[{"symbol": "BTCUSDT"}],
        ).to_dict()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Feature fetch failed: {exc}") from exc

    # 2. Build float32 numpy array in FEATURE_NAMES order
    feature_values = []
    for name in FEATURE_NAMES:
        val = feature_vector.get(name, [None])[0]
        if val is None:
            raise HTTPException(status_code=503, detail=f"Missing feature: {name}")
        feature_values.append(float(val))

    X = np.array([feature_values], dtype=np.float32)

    # 3. Run ONNX inference
    outputs = ort_session.run(_output_names, {_input_name: X})
    # outputs[0] = label array [[int]], outputs[1] = probability array [[p0, p1]]
    label_int = int(outputs[0][0])
    prob_volatile = float(outputs[1][0][1])  # P(VOLATILE)

    # 4. Map integer label to string
    prediction = "VOLATILE" if label_int == 1 else "CALM"

    # 5. Write prediction to DynamoDB
    pred_id = str(uuid4())
    now = datetime.utcnow()
    ttl_epoch = int(time.time()) + (30 * 24 * 3600)  # 30-day TTL

    try:
        ddb_table.put_item(
            Item={
                "prediction_id": pred_id,
                "timestamp": now.isoformat() + "Z",
                "features": {k: Decimal(str(v)) for k, v in zip(FEATURE_NAMES, feature_values)},
                "prediction": prediction,
                "probability": Decimal(str(prob_volatile)),
                "model_version": model_version,
                "ttl": ttl_epoch,
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DynamoDB write failed: {exc}") from exc

    # 6. Return response (no actual_label at creation time)
    return {
        "prediction": prediction,
        "probability": prob_volatile,
        "prediction_id": pred_id,
        "model_version": model_version,
    }


# ---------------------------------------------------------------------------
# Mangum handler for AWS Lambda (lifespan="off" — no startup/shutdown events)
# ---------------------------------------------------------------------------

handler = Mangum(app, lifespan="off")
