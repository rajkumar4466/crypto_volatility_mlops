"""Materialize features from Feast offline store (S3) to online store (Redis).

Renders feature_store.yaml at runtime with actual env var values,
matching the pattern used by the serving Lambda.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("PROJECT_ROOT", "/home/ec2-user/crypto_volatility_mlops"))

from datetime import datetime, timezone
from pathlib import Path
from feast import FeatureStore

# Required env vars
S3_BUCKET = os.environ["S3_BUCKET"]
REDIS_HOST = os.environ["REDIS_HOST"]
REDIS_PORT = os.environ.get("REDIS_PORT", "6379")

# Render feature_store.yaml with actual values
yaml_content = f"""project: crypto_volatility
registry: s3://{S3_BUCKET}/feast/registry.pb
provider: aws
online_store:
  type: redis
  connection_string: "{REDIS_HOST}:{REDIS_PORT}"
offline_store:
  type: file
entity_key_serialization_version: 3
"""

# Write rendered YAML to a temp directory alongside a copy of features.py
tmp_repo = tempfile.mkdtemp(prefix="feast_repo_")
yaml_path = os.path.join(tmp_repo, "feature_store.yaml")
with open(yaml_path, "w") as f:
    f.write(yaml_content)

# Copy features.py into the temp repo so Feast can discover feature definitions
import shutil
project_root = os.environ.get("PROJECT_ROOT", "/home/ec2-user/crypto_volatility_mlops")
src_features = os.path.join(project_root, "feast", "features.py")
shutil.copy2(src_features, os.path.join(tmp_repo, "features.py"))

# Also need to set FEAST_S3_BUCKET so features.py resolves the FileSource path correctly
os.environ["FEAST_S3_BUCKET"] = S3_BUCKET

store = FeatureStore(repo_path=tmp_repo)

# Full materialize from a far-back start date to cover all data
start = datetime(2020, 1, 1, tzinfo=timezone.utc)
end = datetime.now(timezone.utc)
print(f"Running feast materialize from {start} to {end}")
print(f"Registry: s3://{S3_BUCKET}/feast/registry.pb")
print(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
print(f"Offline source: s3://{S3_BUCKET}/feast/offline/btc_features/")

store.materialize(start_date=start, end_date=end)

# Verify data actually landed in Redis
from src.features.store import spot_check_online_store
result = spot_check_online_store(store=store)

# Check which features are null in Redis
null_features = [
    k for k, v in result.items()
    if k != "symbol" and (v is None or (isinstance(v, list) and v[0] is None))
]
null_count = len(null_features)

# Sentiment features may be null due to external API failures — warn but don't block
SENTIMENT_FEATURES = {"fear_greed", "market_cap_change_24h", "btc_dominance"}
critical_nulls = [f for f in null_features if f not in SENTIMENT_FEATURES]

if critical_nulls:
    raise RuntimeError(
        f"Materialization produced {len(critical_nulls)} null CORE features in Redis: "
        f"{critical_nulls}. Check that offline store has data and Redis is reachable."
    )

if null_features:
    print(f"WARNING: {null_count} sentiment features null in Redis (non-blocking): {null_features}")
else:
    print(f"Materialize complete: all features verified in Redis")
