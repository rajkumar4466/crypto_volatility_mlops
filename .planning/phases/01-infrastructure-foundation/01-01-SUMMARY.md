---
phase: 01-infrastructure-foundation
plan: 01
subsystem: infra
tags: [terraform, aws, ec2, rds, elasticache, lambda, api-gateway, s3, dynamodb, sns, cloudwatch, ecr, vpc]

# Dependency graph
requires: []
provides:
  - Terraform IaC for all 10 AWS service types (ECR, EC2, RDS, ElastiCache, Lambda, API Gateway, S3, DynamoDB, SNS, CloudWatch)
  - 5 Terraform modules: billing, network, storage, compute, serverless
  - Lifecycle scripts: spin_up.sh, tear_down.sh, audit_orphans.sh, push_stub_image.sh
  - VPC with public + private subnets, 4 security groups (airflow, rds, redis, lambda)
  - Billing alarm at $1 threshold in us-east-1 via provider alias
affects: [02-data-feature-pipeline, 03-model-training, 04-serving-api, 05-airflow-orchestration, 06-monitoring-drift, 07-cicd-pipeline]

# Tech tracking
tech-stack:
  added: [terraform >= 1.5, hashicorp/aws ~> 5.0, hashicorp/random ~> 3.0]
  patterns:
    - Modular Terraform structure with separate billing/network/storage/compute/serverless modules
    - Billing alarm applied first unconditionally via targeted apply in spin_up.sh
    - Provider alias (aws.billing) for us-east-1 billing metrics
    - SG chaining (lambda SG references redis SG, not CIDR) for VPC security
    - Swap-first user_data pattern (fallocate before any dnf install)

key-files:
  created:
    - infra/providers.tf
    - infra/variables.tf
    - infra/outputs.tf
    - infra/main.tf
    - infra/modules/billing/main.tf
    - infra/modules/network/main.tf
    - infra/modules/storage/main.tf
    - infra/modules/compute/main.tf
    - infra/modules/serverless/main.tf
    - scripts/spin_up.sh
    - scripts/tear_down.sh
    - scripts/audit_orphans.sh
    - scripts/push_stub_image.sh
    - .gitignore
  modified: []

key-decisions:
  - "hashicorp/aws ~> 5.0 chosen (v4 EOL); random provider added for unique S3 bucket suffix"
  - "Lambda architectures = x86_64 only — ARM64 has ONNX Runtime illegal instruction bug (pre-existing STATE.md decision)"
  - "DynamoDB PROVISIONED billing mode (5 RCU/5 WCU) — PAY_PER_REQUEST disqualifies always-free 25 WCU/RCU tier"
  - "ElastiCache aws_elasticache_cluster (cache.t3.micro) not Serverless — Serverless is NOT free-tier eligible"
  - "RDS skip_final_snapshot=true + deletion_protection=false — enables clean terraform destroy without manual intervention"
  - "EC2 uses dnf (not yum or amazon-linux-extras) — Amazon Linux 2023 requirement"
  - "API Gateway HTTP API v2 (aws_apigatewayv2_api) not REST API v1 — 70% cheaper, simpler for GET endpoints"
  - "Lambda SG egress to Redis via security group reference not CIDR — prevents breakage on restart"
  - "Local Terraform state (not S3 remote) — simplest for Phase 1; remote backend deferred to Phase 7"

patterns-established:
  - "Billing-first apply: always terraform apply -target=module.billing before any other resource"
  - "Swap-first user_data: fallocate 4G before any dnf/docker installs in EC2 bootstrap"
  - "SG chaining: reference SG IDs (not CIDR) for intra-VPC service access"
  - "force_destroy/force_delete on S3 and ECR — enables clean destroy without manual intervention"
  - "Separate SNS topics for billing (us-east-1) and drift (deployment region)"

requirements-completed: [INFRA-01, INFRA-02, INFRA-03, INFRA-05]

# Metrics
duration: 5min
completed: 2026-03-12
---

# Phase 1 Plan 01: Terraform IaC for All AWS Resources Summary

**5-module Terraform project provisioning all 10 AWS services (EC2, RDS, ElastiCache, Lambda, API Gateway, S3, DynamoDB, SNS x2, CloudWatch) with billing-first lifecycle scripts and a $1 billing alarm in us-east-1**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-12T22:21:47Z
- **Completed:** 2026-03-12T22:26:42Z
- **Tasks:** 2 of 2
- **Files created:** 30 (26 Terraform HCL + 4 bash scripts)

## Accomplishments

- Complete Terraform project structure with 5 modules (billing, network, storage, compute, serverless) covering all 10 required AWS service types; `terraform validate` passes with zero errors
- Billing alarm module using provider alias `aws.billing` (us-east-1) fires at $1 EstimatedCharges — applied first unconditionally via spin_up.sh targeting
- 4 lifecycle scripts: spin_up.sh (billing-first apply order), tear_down.sh (destroy + orphan audit), audit_orphans.sh (EBS, EIPs, RDS snapshots, EC2), push_stub_image.sh (ECR stub for Lambda bootstrap)
- EC2 user_data configures 4GB swap with fallocate before any dnf/Docker installs; RDS has skip_final_snapshot=true and deletion_protection=false for clean destroy

## Task Commits

Each task was committed atomically:

1. **Task 1: Terraform root config, billing, network, storage modules** - `d6213ba` (feat)
2. **Task 2: Compute module, serverless module, lifecycle scripts** - `a399d0b` (committed with docs research files)

## Files Created/Modified

- `infra/providers.tf` - AWS default provider + us-east-1 billing alias, required_version >= 1.5
- `infra/variables.tf` - 6 root variables (aws_region, project_name, alert_email, db_username, db_password, ec2_key_name)
- `infra/main.tf` - Root module calling all 5 sub-modules with wired outputs
- `infra/outputs.tf` - 10 root outputs exported (ec2_ip, rds, redis, s3, ecr, api_url, dynamodb, sns ARNs)
- `infra/modules/billing/main.tf` - SNS topic + email subscription + CloudWatch billing alarm ($1, 6h period, us-east-1)
- `infra/modules/network/main.tf` - VPC 10.0.0.0/16, 2 public + 2 private subnets, IGW, route tables, 4 SGs with SG chaining
- `infra/modules/storage/main.tf` - S3 bucket (versioned, random suffix), ECR repo (force_delete), DynamoDB PROVISIONED 5/5 with TTL
- `infra/modules/compute/main.tf` - EC2 t3.micro (AL2023, 4GB swap + Docker via dnf), RDS PostgreSQL 16, ElastiCache Redis 7.1
- `infra/modules/serverless/main.tf` - Lambda x86_64 stub (package=Image, 512MB, VPC), API Gateway v2, IAM role, SNS drift topic
- `scripts/spin_up.sh` - 7-step spin-up with billing-first apply, SNS confirmation prompt, stub image push
- `scripts/tear_down.sh` - terraform destroy then audit_orphans.sh call
- `scripts/audit_orphans.sh` - AWS CLI checks: EBS snapshots, unassociated EIPs, manual RDS snapshots, running EC2
- `scripts/push_stub_image.sh` - Pulls public.ecr.aws/lambda/python:3.11, tags and pushes to private ECR as :latest
- `.gitignore` - Excludes .terraform/, state files, terraform.tfvars, Python artifacts, ML artifacts

## Decisions Made

- **x86_64 Lambda only**: ARM64 excluded due to ONNX Runtime illegal instruction bug (documented in STATE.md from pre-execution research)
- **DynamoDB PROVISIONED**: PAY_PER_REQUEST disqualifies from always-free 25 WCU/RCU tier
- **EC2 uses dnf**: Amazon Linux 2023 dropped yum and amazon-linux-extras; dnf is the package manager
- **SG chaining over CIDR**: Lambda SG egress references Redis SG ID directly to survive instance restarts
- **Local Terraform state**: Simplest for Phase 1; S3 remote backend deferred to Phase 7 CI/CD

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created compute and serverless modules during Task 1 to unblock terraform validate**
- **Found during:** Task 1 verification (terraform validate)
- **Issue:** `terraform validate` validates all modules simultaneously. The root `main.tf` references the compute and serverless modules, which had no `variables.tf` files yet — causing "Unsupported argument" errors on 8 arguments
- **Fix:** Created `infra/modules/compute/` and `infra/modules/serverless/` (variables.tf, main.tf, outputs.tf) as part of the Task 1 verification step, before the Task 2 commit
- **Files modified:** infra/modules/compute/*, infra/modules/serverless/*
- **Verification:** `terraform validate` passes with "Success! The configuration is valid."
- **Committed in:** a399d0b (included with docs research commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking)
**Impact on plan:** Necessary for validation to pass; all Task 2 content was created as specified. No scope creep.

## Issues Encountered

- Task 2 files were inadvertently committed alongside the docs(07) CI/CD research commit due to git staging. All files were correctly created and pass all validation criteria — only the commit message context was non-ideal.

## User Setup Required

Before running `scripts/spin_up.sh`, users must:
1. Configure `infra/terraform.tfvars` with `alert_email`, `db_password`, and `ec2_key_name`
2. Ensure AWS CLI is configured (`aws configure` or environment variables)
3. Verify Docker Desktop is running (needed for `push_stub_image.sh`)
4. Check email and click SNS subscription confirmation link after billing module applies
5. Verify ElastiCache free-tier eligibility (accounts created after July 15, 2025 may incur charges)

## Next Phase Readiness

- All AWS resource definitions ready for Phase 2 (Feast feature store, S3 offline store, ElastiCache online store)
- S3 bucket, DynamoDB table, and ECR repository names available as Terraform outputs
- VPC, subnet IDs, and security group IDs exported for Phase 4 Lambda VPC config
- ElastiCache free-tier eligibility remains an open concern to verify before spin-up

---
*Phase: 01-infrastructure-foundation*
*Completed: 2026-03-12*
