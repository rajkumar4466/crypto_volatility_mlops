"""Airflow wrapper: Retrain model using training/train.py logic."""
import os
import sys
import subprocess

project_root = os.environ.get("PROJECT_ROOT", "/home/ec2-user/crypto_volatility_mlops")

env = os.environ.copy()
env["WANDB_MODE"] = env.get("WANDB_MODE", "offline")
env["TMPDIR"] = "/var/tmp"

print("Starting model retraining...")
result = subprocess.run(
    [sys.executable, "-m", "training.train"],
    cwd=project_root,
    env=env,
    capture_output=True,
    text=True,
)

if result.stdout:
    print(result.stdout)
if result.stderr:
    print(result.stderr)

sys.exit(result.returncode)
