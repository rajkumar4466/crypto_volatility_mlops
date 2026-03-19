"""Airflow wrapper: Promote challenger model to champion if it outperforms.

Copies challenger.onnx -> current.onnx and challenger_metrics.json -> current_metrics.json
only if challenger F1 > champion F1.
"""
import os
import sys
import json
import boto3

bucket = os.environ["S3_BUCKET"]
s3 = boto3.client("s3")


def load_metrics(key):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except Exception:
        return None


champion = load_metrics("models/current_metrics.json")
challenger = load_metrics("models/challenger_metrics.json")

if challenger is None:
    print("No challenger model — nothing to promote.")
    sys.exit(0)

champ_f1 = champion.get("f1", 0) if champion else 0
chall_f1 = challenger.get("f1", 0)

if chall_f1 <= champ_f1:
    print(f"Challenger F1 ({chall_f1:.4f}) <= Champion F1 ({champ_f1:.4f}) — no promotion.")
    sys.exit(0)

print(f"Promoting challenger (F1={chall_f1:.4f}) over champion (F1={champ_f1:.4f})...")

# Copy challenger -> current
s3.copy_object(
    Bucket=bucket,
    CopySource={"Bucket": bucket, "Key": "models/challenger.onnx"},
    Key="models/current.onnx",
)
s3.copy_object(
    Bucket=bucket,
    CopySource={"Bucket": bucket, "Key": "models/challenger_metrics.json"},
    Key="models/current_metrics.json",
)

print("Promotion complete: challenger is now the champion.")
