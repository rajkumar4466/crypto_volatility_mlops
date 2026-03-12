#!/bin/bash
# audit_orphans.sh — Detect AWS resources that may have been created outside Terraform
# or not cleaned up by terraform destroy
# Run after tear_down.sh or anytime you suspect cost leakage

set -e

REGION="${AWS_DEFAULT_REGION:-us-east-2}"
PROJECT="${PROJECT_NAME:-crypto-vol}"

echo "=== Auditing for orphaned AWS resources ==="
echo "Region: ${REGION}"
echo "Project tag: ${PROJECT}"
echo ""

# Check for orphaned EBS snapshots with project tag
echo "--- EBS Snapshots (tagged Project=${PROJECT}) ---"
aws ec2 describe-snapshots \
  --owner-ids self \
  --filters "Name=tag:Project,Values=${PROJECT}" \
  --query 'Snapshots[*].[SnapshotId,StartTime,VolumeSize]' \
  --output table \
  --region "${REGION}" 2>/dev/null || echo "(none or error)"

echo ""

# Check for unassociated Elastic IPs (these cost money when not attached)
echo "--- Unassociated Elastic IPs ---"
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp]' \
  --output table \
  --region "${REGION}" 2>/dev/null || echo "(none or error)"

echo ""

# Check for manual RDS snapshots
echo "--- Manual RDS Snapshots ---"
aws rds describe-db-snapshots \
  --snapshot-type manual \
  --query 'DBSnapshots[*].[DBSnapshotIdentifier,SnapshotCreateTime,Status]' \
  --output table \
  --region "${REGION}" 2>/dev/null || echo "(none or error)"

echo ""

# Check for running or stopped EC2 instances with project tag
echo "--- Running/Stopped EC2 Instances (tagged Project=${PROJECT}) ---"
aws ec2 describe-instances \
  --filters "Name=instance-state-name,Values=running,stopped" \
             "Name=tag:Project,Values=${PROJECT}" \
  --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name]' \
  --output table \
  --region "${REGION}" 2>/dev/null || echo "(none or error)"

echo ""
echo "=== Audit complete ==="
echo "If any resources are listed above, delete them manually to avoid charges."
