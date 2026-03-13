#!/usr/bin/env bash
# push_backfill_image.sh — Build and push the backfill Lambda container to ECR
# Usage: ./scripts/push_backfill_image.sh <ecr_url>
# Example: ./scripts/push_backfill_image.sh 123456789.dkr.ecr.us-east-2.amazonaws.com/crypto-vol-predictor

set -euo pipefail

ECR_URL="${1:-}"
if [[ -z "$ECR_URL" ]]; then
  # Try to get from Terraform output
  ECR_URL=$(cd infra && terraform output -raw ecr_repository_url 2>/dev/null || echo "")
fi

if [[ -z "$ECR_URL" ]]; then
  echo "ERROR: ECR URL required. Pass as argument or run 'terraform apply' first."
  exit 1
fi

AWS_REGION=$(cd infra && terraform output -raw aws_region 2>/dev/null || echo "us-east-2")
AWS_ACCOUNT=$(echo "$ECR_URL" | cut -d. -f1)

echo "Logging in to ECR..."
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ECR_URL"

echo "Building backfill image (linux/amd64)..."
cd serving/

# Build the backfill image using Dockerfile.backfill
docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  -t "${ECR_URL}:backfill-latest" \
  -f Dockerfile.backfill \
  .

echo "Pushing backfill image..."
docker push "${ECR_URL}:backfill-latest"

echo "Done. Backfill image pushed to ${ECR_URL}:backfill-latest"
