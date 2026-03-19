"""Airflow wrapper: Compute features from raw OHLCV data and write to Feast offline store path."""
import os
import sys

sys.path.insert(0, os.environ.get("PROJECT_ROOT", "/home/ec2-user/crypto_volatility_mlops"))

import boto3
import io
import pandas as pd
from src.features.compute import compute_features
from src.features.labels import label_volatility

bucket = os.environ["S3_BUCKET"]
s3 = boto3.client("s3")

# Find the latest raw parquet file
paginator = s3.get_paginator("list_objects_v2")
pages = paginator.paginate(Bucket=bucket, Prefix="raw/btc_ohlcv/")
keys = sorted(
    [obj["Key"] for page in pages for obj in page.get("Contents", []) if obj["Key"].endswith(".parquet")],
    reverse=True,
)

if not keys:
    print("No raw data files found in S3. Skipping feature computation.")
    sys.exit(0)

print(f"Loading latest raw file: s3://{bucket}/{keys[0]}")
obj = s3.get_object(Bucket=bucket, Key=keys[0])
df = pd.read_parquet(io.BytesIO(obj["Body"].read()))

print(f"Computing features on {len(df)} rows...")
df_feat = compute_features(df)
df_feat = df_feat.dropna()
print(f"{len(df_feat)} rows after dropping NaN warm-up rows")

# Apply labels
df_labeled = label_volatility(df_feat)
print(f"{len(df_labeled)} rows after labeling (last 30 dropped)")

# Add Feast-required columns
df_labeled["event_timestamp"] = pd.to_datetime(df_labeled["timestamp"], unit="ms", utc=True)
df_labeled["created_timestamp"] = df_labeled["event_timestamp"]
df_labeled["symbol"] = "BTCUSDT"

# Write to the S3 path Feast FileSource reads from
out_key = "feast/offline/btc_features/features.parquet"
buf = io.BytesIO()
df_labeled.to_parquet(buf, index=False)
buf.seek(0)
s3.put_object(Bucket=bucket, Key=out_key, Body=buf.getvalue())
print(f"Wrote {len(df_labeled)} rows to s3://{bucket}/{out_key}")
