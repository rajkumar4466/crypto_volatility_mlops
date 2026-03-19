#!/bin/bash
# audit_orphans.sh — Comprehensive audit for AWS resources that may survive terraform destroy
#
# Checks ALL resource types used by this project:
#   EC2, EBS, RDS, ElastiCache, Lambda, API Gateway, S3, DynamoDB,
#   ECR, SNS, CloudWatch, EventBridge, VPC, IAM, Elastic IPs
#
# Run after tear_down.sh or anytime you suspect cost leakage

set -e

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
PROJECT="${PROJECT_NAME:-crypto-vol}"
FOUND=0

echo "=== Auditing for orphaned AWS resources ==="
echo "Region: ${REGION}"
echo "Project prefix: ${PROJECT}"
echo ""

# --- EC2 Instances ---
echo "--- EC2 Instances ---"
RESULT=$(aws ec2 describe-instances \
    --filters "Name=instance-state-name,Values=running,stopped" \
              "Name=tag:Project,Values=${PROJECT}" \
    --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name]' \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- EBS Volumes (unattached) ---
echo "--- Unattached EBS Volumes ---"
RESULT=$(aws ec2 describe-volumes \
    --filters "Name=status,Values=available" \
    --query 'Volumes[*].[VolumeId,Size,State]' \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- EBS Snapshots ---
echo "--- EBS Snapshots (tagged Project=${PROJECT}) ---"
RESULT=$(aws ec2 describe-snapshots \
    --owner-ids self \
    --filters "Name=tag:Project,Values=${PROJECT}" \
    --query 'Snapshots[*].[SnapshotId,StartTime,VolumeSize]' \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- Elastic IPs (unassociated = costs money) ---
echo "--- Unassociated Elastic IPs ---"
RESULT=$(aws ec2 describe-addresses \
    --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp]' \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND (these cost ~\$3.65/month each): ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- RDS Instances ---
echo "--- RDS Instances (${PROJECT}-*) ---"
RESULT=$(aws rds describe-db-instances \
    --query "DBInstances[?starts_with(DBInstanceIdentifier,'${PROJECT}')].[DBInstanceIdentifier,DBInstanceStatus,DBInstanceClass]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- RDS Snapshots (manual) ---
echo "--- Manual RDS Snapshots ---"
RESULT=$(aws rds describe-db-snapshots \
    --snapshot-type manual \
    --query "DBSnapshots[?starts_with(DBSnapshotIdentifier,'${PROJECT}')].[DBSnapshotIdentifier,Status]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- ElastiCache Clusters ---
echo "--- ElastiCache Clusters (${PROJECT}-*) ---"
RESULT=$(aws elasticache describe-cache-clusters \
    --query "CacheClusters[?starts_with(CacheClusterId,'${PROJECT}')].[CacheClusterId,CacheNodeType,CacheClusterStatus]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- Lambda Functions ---
echo "--- Lambda Functions (${PROJECT}-*) ---"
RESULT=$(aws lambda list-functions \
    --query "Functions[?starts_with(FunctionName,'${PROJECT}')].[FunctionName,Runtime,MemorySize]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- API Gateway ---
echo "--- API Gateway APIs (${PROJECT}-*) ---"
RESULT=$(aws apigatewayv2 get-apis \
    --query "Items[?starts_with(Name,'${PROJECT}')].[ApiId,Name]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- S3 Buckets ---
echo "--- S3 Buckets (${PROJECT}-*) ---"
RESULT=$(aws s3api list-buckets \
    --query "Buckets[?starts_with(Name,'${PROJECT}')].[Name,CreationDate]" \
    --output text 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- DynamoDB Tables ---
echo "--- DynamoDB Tables (${PROJECT}-*) ---"
RESULT=$(aws dynamodb list-tables \
    --query "TableNames[?starts_with(@,'${PROJECT}')]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- ECR Repositories ---
echo "--- ECR Repositories (${PROJECT}-*) ---"
RESULT=$(aws ecr describe-repositories \
    --query "repositories[?starts_with(repositoryName,'${PROJECT}')].[repositoryName,repositoryUri]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- SNS Topics ---
echo "--- SNS Topics (${PROJECT}-*) ---"
RESULT=$(aws sns list-topics \
    --query "Topics[?contains(TopicArn,'${PROJECT}')].[TopicArn]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
# Also check us-east-1 for billing alarm SNS topic
if [ "${REGION}" != "us-east-1" ]; then
    RESULT_BILLING=$(aws sns list-topics \
        --query "Topics[?contains(TopicArn,'${PROJECT}')].[TopicArn]" \
        --output text --region "us-east-1" 2>/dev/null || echo "")
    if [ -n "${RESULT_BILLING}" ]; then
        echo "  FOUND (us-east-1 billing): ${RESULT_BILLING}"
        FOUND=$((FOUND + 1))
    fi
fi
echo ""

# --- CloudWatch Alarms ---
echo "--- CloudWatch Alarms (${PROJECT}-* or CryptoVolatility) ---"
RESULT=$(aws cloudwatch describe-alarms \
    --query "MetricAlarms[?starts_with(AlarmName,'${PROJECT}') || starts_with(Namespace,'CryptoVolatility')].[AlarmName,StateValue]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
# Check us-east-1 for billing alarm
RESULT_BILLING=$(aws cloudwatch describe-alarms \
    --alarm-name-prefix "${PROJECT}" \
    --query "MetricAlarms[*].[AlarmName,StateValue]" \
    --output text --region "us-east-1" 2>/dev/null || echo "")
if [ -n "${RESULT_BILLING}" ]; then
    echo "  FOUND (us-east-1 billing): ${RESULT_BILLING}"
    FOUND=$((FOUND + 1))
fi
echo ""

# --- CloudWatch Dashboards ---
echo "--- CloudWatch Dashboards ---"
RESULT=$(aws cloudwatch list-dashboards \
    --dashboard-name-prefix "${PROJECT}" \
    --query "DashboardEntries[*].[DashboardName]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- EventBridge Schedules ---
echo "--- EventBridge Schedules (${PROJECT}-*) ---"
RESULT=$(aws scheduler list-schedules \
    --name-prefix "${PROJECT}" \
    --query "Schedules[*].[Name,State]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- VPCs (non-default) ---
echo "--- VPCs (tagged Project=${PROJECT}) ---"
RESULT=$(aws ec2 describe-vpcs \
    --filters "Name=tag:Project,Values=${PROJECT}" \
    --query "Vpcs[*].[VpcId,CidrBlock,State]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- IAM Roles ---
echo "--- IAM Roles (${PROJECT}-*) ---"
RESULT=$(aws iam list-roles \
    --query "Roles[?starts_with(RoleName,'${PROJECT}')].[RoleName,CreateDate]" \
    --output text 2>/dev/null || echo "")
if [ -n "${RESULT}" ]; then
    echo "  FOUND: ${RESULT}"
    FOUND=$((FOUND + 1))
else
    echo "  None"
fi
echo ""

# --- Summary ---
echo "=========================================="
if [ ${FOUND} -eq 0 ]; then
    echo "  All clear! No orphaned resources found."
else
    echo "  WARNING: ${FOUND} resource type(s) still exist."
    echo "  Delete them manually or re-run terraform destroy."
fi
echo "=========================================="
echo ""
echo "Also verify your bill at: https://console.aws.amazon.com/billing/"
