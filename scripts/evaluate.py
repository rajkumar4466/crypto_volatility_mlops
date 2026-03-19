"""Airflow wrapper: Evaluate challenger model vs champion.

Compares current_metrics.json (champion) against challenger_metrics.json.
If challenger has better F1, signals promotion. Otherwise, exits cleanly.
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
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as e:
        print(f"Error loading {key}: {e}")
        return None


champion = load_metrics("models/current_metrics.json")
challenger = load_metrics("models/challenger_metrics.json")

if challenger is None:
    print("No challenger model found — nothing to evaluate.")
    sys.exit(0)

if champion is None:
    print("No champion model found — challenger wins by default.")
    sys.exit(0)

champ_f1 = champion.get("f1", 0)
chall_f1 = challenger.get("f1", 0)

print(f"Champion F1: {champ_f1:.4f}")
print(f"Challenger F1: {chall_f1:.4f}")

if chall_f1 > champ_f1:
    print("Challenger outperforms champion — flagging for promotion.")
else:
    print("Champion still better — no promotion needed.")
