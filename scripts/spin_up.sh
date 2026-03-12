#!/bin/bash
# spin_up.sh — Full infrastructure bring-up in correct order
# Order is non-negotiable:
#   1. Billing alarm first (INFRA-03 requirement)
#   2. Network + Storage (infrastructure base)
#   3. Push stub Lambda image to ECR
#   4. Compute + Serverless (billable resources)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/../infra"

echo "=== Crypto Volatility MLOps — Spin Up ==="
echo "Infra dir: ${INFRA_DIR}"

# Step 1: Initialize Terraform
echo ""
echo "--- Step 1: Terraform Init ---"
cd "${INFRA_DIR}"
terraform init

# Step 2: Apply billing alarm FIRST (non-negotiable — before any billable resource)
echo ""
echo "--- Step 2: Apply Billing Alarm (us-east-1, fires at \$1) ---"
terraform apply -target=module.billing -auto-approve

# Step 3: Remind user to confirm SNS email subscription
echo ""
echo "--- Step 3: ACTION REQUIRED ---"
echo "  An SNS subscription confirmation email was sent to your alert_email."
echo "  Please check your inbox and click 'Confirm subscription' NOW."
echo "  The billing alarm will NOT fire until you confirm."
echo ""
echo "  Press ENTER when you have confirmed the email subscription..."
read -r

# Step 4: Apply network and storage (infrastructure base, no images needed yet)
echo ""
echo "--- Step 4: Apply Network + Storage ---"
terraform apply -target=module.network -target=module.storage -auto-approve

# Step 5: Push stub Lambda image to ECR (Lambda requires a valid image at apply time)
echo ""
echo "--- Step 5: Push Stub Lambda Image to ECR ---"
cd "${SCRIPT_DIR}"
bash push_stub_image.sh

# Step 6: Apply compute and serverless (billable — ECR image now exists)
echo ""
echo "--- Step 6: Apply Compute + Serverless ---"
cd "${INFRA_DIR}"
terraform apply -auto-approve

# Step 7: Display all endpoints
echo ""
echo "--- Step 7: Infrastructure Outputs ---"
terraform output

echo ""
echo "=== Spin up complete. Remember to run tear_down.sh when done. ==="
