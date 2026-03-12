#!/usr/bin/env bash
# feast_setup.sh — Run once after Phase 1 infrastructure is live.
# Prerequisites: FEAST_S3_BUCKET, REDIS_HOST, REDIS_PORT, AWS_REGION env vars set.
set -euo pipefail

echo "=== Feast Setup: Phase 2 ==="
echo "Bucket: ${FEAST_S3_BUCKET}"
echo "Redis: ${REDIS_HOST}:${REDIS_PORT}"

# 1. Register feature definitions in S3 registry
echo "--- feast apply ---"
cd "$(dirname "$0")/.."
feast -c feast/ apply

echo "--- Verifying registry ---"
feast -c feast/ feature-views list

echo "=== Setup complete. Next: run ingest -> feature pipeline -> write_to_feast_offline -> run_materialize ==="
