#!/bin/bash
# push_stub_image.sh — Push a placeholder Lambda image to ECR
# Required before applying the serverless module (Lambda requires a valid image at apply time)
# Source image: public.ecr.aws/lambda/python:3.11

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/../infra"

echo "=== Pushing stub Lambda image to ECR ==="

# Get ECR repository URL from Terraform output
cd "${INFRA_DIR}"
ECR_URL=$(terraform output -raw ecr_repository_url)
echo "ECR repository: ${ECR_URL}"

# Extract region and account from ECR URL
# Format: <account-id>.dkr.ecr.<region>.amazonaws.com/<name>
AWS_ACCOUNT=$(echo "${ECR_URL}" | cut -d. -f1)
AWS_REGION=$(echo "${ECR_URL}" | cut -d. -f4)

echo "Region: ${AWS_REGION}"
echo "Account: ${AWS_ACCOUNT}"

# Authenticate Docker with ECR
echo "Authenticating with ECR..."
aws ecr get-login-password --region "${AWS_REGION}" | \
  docker login --username AWS --password-stdin "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Pull the public Lambda Python base image
STUB_IMAGE="public.ecr.aws/lambda/python:3.11"
echo "Pulling stub image: ${STUB_IMAGE}"
docker pull "${STUB_IMAGE}"

# Tag and push to private ECR as :latest
echo "Tagging and pushing to ${ECR_URL}:latest"
docker tag "${STUB_IMAGE}" "${ECR_URL}:latest"
docker push "${ECR_URL}:latest"

echo "=== Stub image pushed successfully to ${ECR_URL}:latest ==="
