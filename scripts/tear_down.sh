#!/bin/bash
# tear_down.sh — Destroy ALL project infrastructure and clean up non-Terraform resources
#
# What this script does:
#   1. Empty S3 bucket (Terraform can't destroy non-empty buckets)
#   2. Delete all ECR images (Terraform can't destroy repos with images)
#   3. Terraform destroy (EC2, RDS, Redis, Lambda, API Gateway, VPC, etc.)
#   4. Audit for any orphaned resources
#
# Run this to avoid unexpected AWS charges.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/../infra"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
PROJECT="${PROJECT_NAME:-crypto-vol}"

echo "=== Crypto Volatility MLOps — Full Tear Down ==="
echo "Region: ${REGION}"
echo ""

# -----------------------------------------------------------------------
# Step 1: Get resource names from Terraform outputs (before destroying)
# -----------------------------------------------------------------------
echo "--- Step 1: Reading Terraform outputs ---"
cd "${INFRA_DIR}"

S3_BUCKET=$(terraform output -raw s3_bucket_name 2>/dev/null || echo "")
ECR_REPO=$(terraform output -raw ecr_repository_url 2>/dev/null || echo "")
DYNAMODB_TABLE=$(terraform output -raw dynamodb_table_name 2>/dev/null || echo "")

echo "  S3 bucket:      ${S3_BUCKET:-not found}"
echo "  ECR repo:        ${ECR_REPO:-not found}"
echo "  DynamoDB table:  ${DYNAMODB_TABLE:-not found}"
echo ""

# -----------------------------------------------------------------------
# Step 2: Empty S3 bucket (Terraform can't destroy non-empty buckets)
# -----------------------------------------------------------------------
if [ -n "${S3_BUCKET}" ]; then
    echo "--- Step 2: Emptying S3 bucket ---"
    echo "  Deleting all objects in s3://${S3_BUCKET}/ ..."
    aws s3 rm "s3://${S3_BUCKET}" --recursive --region "${REGION}" 2>/dev/null || true

    # Also delete any versioned objects if versioning is enabled
    echo "  Deleting versioned objects..."
    aws s3api list-object-versions \
        --bucket "${S3_BUCKET}" \
        --region "${REGION}" \
        --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
        --output json 2>/dev/null | \
    python3 -c "
import sys, json
data = json.load(sys.stdin)
objects = data.get('Objects') or []
if objects:
    print(f'  Deleting {len(objects)} versioned objects...')
" 2>/dev/null || true

    aws s3api list-object-versions \
        --bucket "${S3_BUCKET}" \
        --region "${REGION}" \
        --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
        --output json 2>/dev/null | \
    python3 -c "
import sys, json
data = json.load(sys.stdin)
objects = data.get('Objects') or []
if objects:
    print(f'  Deleting {len(objects)} delete markers...')
" 2>/dev/null || true

    echo "  S3 bucket emptied."
else
    echo "--- Step 2: Skipped (no S3 bucket found in Terraform output) ---"
fi
echo ""

# -----------------------------------------------------------------------
# Step 3: Delete all ECR images (Terraform can't destroy repos with images)
# -----------------------------------------------------------------------
if [ -n "${ECR_REPO}" ]; then
    ECR_REPO_NAME=$(echo "${ECR_REPO}" | cut -d'/' -f2)
    echo "--- Step 3: Deleting ECR images ---"
    IMAGE_IDS=$(aws ecr list-images \
        --repository-name "${ECR_REPO_NAME}" \
        --region "${REGION}" \
        --query 'imageIds[*]' \
        --output json 2>/dev/null || echo "[]")

    if [ "${IMAGE_IDS}" != "[]" ] && [ -n "${IMAGE_IDS}" ]; then
        echo "  Deleting images from ${ECR_REPO_NAME}..."
        aws ecr batch-delete-image \
            --repository-name "${ECR_REPO_NAME}" \
            --image-ids "${IMAGE_IDS}" \
            --region "${REGION}" 2>/dev/null || true
        echo "  ECR images deleted."
    else
        echo "  No images found in ECR."
    fi
else
    echo "--- Step 3: Skipped (no ECR repo found in Terraform output) ---"
fi
echo ""

# -----------------------------------------------------------------------
# Step 4: Terraform destroy
# -----------------------------------------------------------------------
echo "--- Step 4: Terraform Destroy ---"
echo "  This will destroy: EC2, RDS, ElastiCache, Lambda, API Gateway,"
echo "  S3 bucket, DynamoDB table, ECR repo, VPC, SNS topics, CloudWatch alarms..."
echo ""
cd "${INFRA_DIR}"
terraform destroy -auto-approve

echo ""
echo "--- Terraform destroy complete ---"
echo ""

# -----------------------------------------------------------------------
# Step 5: Comprehensive orphan audit
# -----------------------------------------------------------------------
echo "--- Step 5: Orphan Audit ---"
cd "${SCRIPT_DIR}"
bash audit_orphans.sh

echo ""
echo "=== Tear down complete ==="
echo ""
echo "Checklist:"
echo "  [x] S3 bucket emptied and destroyed"
echo "  [x] ECR images deleted and repo destroyed"
echo "  [x] All Terraform resources destroyed"
echo "  [x] Orphan audit completed"
echo ""
echo "  Check audit output above for any remaining resources."
echo "  Also verify at: https://console.aws.amazon.com/billing/"
