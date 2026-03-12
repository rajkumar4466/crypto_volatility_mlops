#!/bin/bash
# tear_down.sh — Destroy all Terraform-managed infrastructure + audit for orphans
# Run this every evening to avoid unexpected AWS charges

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/../infra"

echo "=== Crypto Volatility MLOps — Tear Down ==="
echo ""

# Step 1: Destroy all Terraform-managed resources
echo "--- Step 1: Terraform Destroy ---"
cd "${INFRA_DIR}"
terraform destroy -auto-approve

echo ""
echo "--- Terraform destroy complete ---"

# Step 2: Audit for orphaned resources (created outside Terraform or not tracked in state)
echo ""
echo "--- Step 2: Orphan Audit ---"
cd "${SCRIPT_DIR}"
bash audit_orphans.sh

echo ""
echo "=== Tear down complete. Check audit output above for any manual cleanup needed. ==="
