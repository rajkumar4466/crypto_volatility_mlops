# Phase 1: Infrastructure Foundation - Research

**Researched:** 2026-03-12
**Domain:** Terraform IaC for AWS free-tier multi-service stack + Docker Compose local dev
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | All AWS resources provisioned via Terraform (ECR, EC2, RDS, ElastiCache, Lambda, API Gateway, S3, DynamoDB, SNS, CloudWatch) | Terraform AWS provider resource types documented for all 10 service types; modular structure pattern researched |
| INFRA-02 | EC2 user-data script configures 2-4GB swap before Airflow starts | EC2 user_data with fallocate/mkswap/swapon/fstab script pattern confirmed; requirement is 4GB per STATE.md decision |
| INFRA-03 | CloudWatch billing alarm triggers at $1 threshold before any resource creation | Billing alarm must be in us-east-1 (provider alias required); EstimatedCharges metric + SNS + email confirmed |
| INFRA-04 | docker-compose.yml for local development and testing of all components | Official Airflow 3.1.8 docker-compose pattern confirmed; services: postgres, redis, airflow-scheduler, airflow-api-server, airflow-worker |
| INFRA-05 | Destroy script (terraform destroy + cleanup of manually-created resources like snapshots, Elastic IPs) | skip_final_snapshot=true + deletion_protection=false on RDS; AWS CLI audit commands for orphaned resources; terraform destroy flow documented |
</phase_requirements>

---

## Summary

Phase 1 creates all AWS infrastructure as Terraform code before any application code runs. The 10 required services (ECR, EC2, RDS, ElastiCache, Lambda stub, API Gateway, S3, DynamoDB, SNS, CloudWatch) span two distinct concerns: ephemeral compute (EC2, RDS, ElastiCache — started/stopped daily) and always-free resources (Lambda, API Gateway, S3, DynamoDB, SNS, CloudWatch — exist continuously at near-zero cost). The Terraform module structure must reflect this split so that `terraform destroy` targets only the billable resources while leaving S3 buckets and ECR repositories intact.

The billing alarm is the non-negotiable first resource created. AWS billing metrics exist only in `us-east-1` regardless of the deployment region, which requires a dedicated Terraform provider alias. The alarm must fire at $1 EstimatedCharges (not $5) and must be applied before any other resource in the stack. This is enforced by putting the billing alarm in a separate `billing/` module that has no dependencies, applied first in the run order.

The docker-compose for local development mirrors the production stack: PostgreSQL (Airflow metadata), Redis (Feast online store), and all Airflow components. The official `apache/airflow:3.1.8` docker-compose provides a complete reference; the project's docker-compose needs to add a Redis service exposed on port 6379 for Feast materialization testing locally.

**Primary recommendation:** Structure Terraform as separate modules per service group (billing, network, storage, compute, serverless). Apply billing module first unconditionally. Set `skip_final_snapshot=true` and `deletion_protection=false` on all RDS and ElastiCache resources. Write an explicit destroy script that runs `terraform destroy`, then audits for orphaned EBS snapshots, Elastic IPs, and RDS snapshots via AWS CLI.

---

## Standard Stack

### Core
| Tool | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Terraform | 1.14.7 | Provision and destroy all AWS resources declaratively | Official HashiCorp IaC tool; `terraform destroy` is the only reliable way to ensure clean teardown of 10 interdependent resources |
| hashicorp/aws provider | ~> 5.x | Terraform AWS provider | Current stable generation; v4 is EOL |
| Docker Compose | v2 (bundled with Docker Desktop) | Local development environment | Defines multi-service stack in single file; official Airflow distribution ships a docker-compose.yaml |

### AWS Services (all free-tier eligible under spin-up/tear-down model)
| Service | Terraform Resource | Free Tier | Notes |
|---------|-------------------|-----------|-------|
| EC2 t3.micro | `aws_instance` | 750 hrs/month (12 months) | Airflow host; requires 4GB swap in user_data |
| RDS db.t3.micro PostgreSQL | `aws_db_instance` | 750 hrs/month (12 months) | Airflow metadata store; `skip_final_snapshot=true`, `deletion_protection=false` |
| ElastiCache cache.t3.micro Redis | `aws_elasticache_cluster` | 750 hrs/month — only if account created before July 15, 2025 | Feast online store; single-node, engine="redis", num_cache_nodes=1 |
| S3 | `aws_s3_bucket` | 5GB always free | Feast offline store, model registry, raw data |
| ECR | `aws_ecr_repository` | 500MB/month always free | Lambda container image storage |
| Lambda | `aws_lambda_function` | 1M invocations always free | Serving stub in Phase 1; x86_64 architecture only (ARM64 has ONNX Runtime bug) |
| API Gateway HTTP API | `aws_apigatewayv2_api` | 1M HTTP calls/month (12 months) | Phase 1: stub; activated in Phase 4 |
| DynamoDB | `aws_dynamodb_table` | 25GB + 25 WCU/25 RCU always free (provisioned mode only) | Prediction logging; use PROVISIONED billing mode to capture free WCU/RCU |
| SNS | `aws_sns_topic` + `aws_sns_topic_subscription` | 1M publishes always free | Billing alerts and drift alerts |
| CloudWatch | `aws_cloudwatch_metric_alarm` | 10 alarms + basic metrics always free | Billing alarm first; custom metrics added in Phase 6 |

### Supporting
| Tool | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| AWS CLI v2 | latest | Post-destroy orphan audit | In destroy script to check for leftover snapshots, Elastic IPs |
| terraform-aws-modules/vpc | ~> 5.0 | VPC with public + private subnets | Use to create consistent VPC for EC2, RDS, ElastiCache, Lambda |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Terraform modules (per-service) | Single flat main.tf | Flat is simpler initially but becomes unmanageable at 10 services; modules allow targeted `terraform destroy -target` |
| `aws_elasticache_cluster` (Classic) | ElastiCache Serverless | Serverless is NOT free-tier eligible; Classic cache.t3.micro is required |
| DynamoDB PROVISIONED | DynamoDB PAY_PER_REQUEST | On-demand does not qualify for free WCU/RCU tier; provisioned with 5 WCU/5 RCU is free and sufficient for Phase 1 volume |
| API Gateway HTTP API (v2) | REST API (v1) | HTTP API is cheaper (1/3 the cost), simpler, and sufficient for GET /predict, GET /health; use `aws_apigatewayv2_api` |

**Installation:**
```bash
# Terraform
brew install terraform  # macOS
terraform --version  # verify 1.x

# AWS CLI
brew install awscli
aws --version

# Docker Compose (bundled with Docker Desktop)
docker compose version
```

---

## Architecture Patterns

### Recommended Terraform Project Structure
```
infra/
├── main.tf               # Root: calls all modules, sets providers
├── variables.tf          # Root-level inputs (region, project_name, etc.)
├── outputs.tf            # Root outputs (ec2_ip, rds_endpoint, redis_endpoint, etc.)
├── terraform.tfvars      # Actual values (gitignored for secrets)
├── providers.tf          # AWS provider + us-east-1 alias for billing
├── modules/
│   ├── billing/          # CloudWatch billing alarm + SNS email (NO dependencies)
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   ├── network/          # VPC, subnets, security groups, internet gateway
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   ├── storage/          # S3 buckets, ECR repository, DynamoDB table
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   ├── compute/          # EC2 t3.micro (Airflow), RDS, ElastiCache — BILLABLE
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   └── serverless/       # Lambda stub, API Gateway stub, SNS topics
│       ├── main.tf
│       ├── variables.tf
│       └── outputs.tf
scripts/
├── spin_up.sh            # terraform apply (compute module only after storage is up)
├── tear_down.sh          # terraform destroy compute + CLI orphan audit
└── audit_orphans.sh      # AWS CLI checks for leaked snapshots, EIPs, etc.
docker-compose.yml        # Local dev: Postgres + Redis + Airflow stack
```

### Pattern 1: Billing Alarm First (INFRA-03)
**What:** CloudWatch billing alarm on `EstimatedCharges` metric, created in `us-east-1` via provider alias, before any other resource
**When to use:** Always — this is the first Terraform apply, unconditionally
**Key constraint:** AWS billing metrics only exist in `us-east-1` regardless of deployment region

```hcl
# Source: Verified against oneuptime.com/blog 2026-02-23 + binbashar module pattern

# providers.tf
provider "aws" {
  region = var.aws_region  # your deployment region e.g. us-east-2
}

provider "aws" {
  alias  = "billing"
  region = "us-east-1"  # billing metrics ONLY available here
}

# modules/billing/main.tf
resource "aws_sns_topic" "billing_alerts" {
  provider = aws.billing
  name     = "${var.project_name}-billing-alerts"
}

resource "aws_sns_topic_subscription" "billing_email" {
  provider  = aws.billing
  topic_arn = aws_sns_topic.billing_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "billing_1_dollar" {
  provider            = aws.billing
  alarm_name          = "${var.project_name}-billing-1-usd"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 21600  # 6 hours (billing metric update frequency)
  statistic           = "Maximum"
  threshold           = 1.0
  dimensions = {
    Currency = "USD"
  }
  alarm_description = "AWS estimated charges exceeded $1"
  alarm_actions     = [aws_sns_topic.billing_alerts.arn]
}
```

### Pattern 2: EC2 with Swap in user_data (INFRA-02)
**What:** Configure 4GB swap file inside EC2 user_data bootstrap script, before Airflow installs
**When to use:** Always on the Airflow EC2 instance — Airflow scheduler needs >1GB RAM headroom on t3.micro

```hcl
# Source: AWS re:Post knowledge-center/ec2-memory-swap-file + nixCraft guide

resource "aws_instance" "airflow" {
  ami           = data.aws_ami.amazon_linux_2.id
  instance_type = "t3.micro"
  subnet_id     = var.public_subnet_id
  vpc_security_group_ids = [aws_security_group.airflow.id]
  key_name      = var.key_name

  user_data = <<-EOF
    #!/bin/bash
    set -e

    # Step 1: Configure swap BEFORE anything else
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab

    # Verify swap is active
    swapon --show

    # Step 2: System updates
    yum update -y

    # Step 3: Install Docker for Airflow container (or install Airflow directly in Phase 5)
    amazon-linux-extras install docker -y
    service docker start
    usermod -a -G docker ec2-user
    systemctl enable docker
  EOF

  root_block_device {
    volume_size = 20  # GB — Airflow logs + Docker images
    volume_type = "gp2"
  }

  tags = {
    Name    = "${var.project_name}-airflow"
    Project = var.project_name
  }
}
```

### Pattern 3: RDS with Clean Destroy Settings (INFRA-05)
**What:** RDS PostgreSQL configured to allow `terraform destroy` without manual snapshot intervention
**When to use:** Any ephemeral RDS instance in a spin-up/tear-down lifecycle

```hcl
# Source: Terraform Registry aws_db_instance + ndench.github.io guide

resource "aws_db_instance" "airflow_metadata" {
  identifier           = "${var.project_name}-airflow-db"
  engine               = "postgres"
  engine_version       = "16.3"
  instance_class       = "db.t3.micro"
  allocated_storage    = 20

  db_name  = "airflow"
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  # CRITICAL for terraform destroy to work without manual intervention:
  skip_final_snapshot = true
  deletion_protection = false

  # Keep backups minimal for dev:
  backup_retention_period = 0
  multi_az                = false

  tags = {
    Name    = "${var.project_name}-airflow-db"
    Project = var.project_name
  }
}
```

### Pattern 4: ElastiCache Single-Node Redis
**What:** Single cache.t3.micro Redis node in private subnet, accessible from Lambda VPC and EC2
**When to use:** Phase 1 stub; Feast online store in Phase 2+

```hcl
# Source: DEV Community + terraform-aws-modules/elasticache pattern

resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project_name}-redis-subnet"
  subnet_ids = var.private_subnet_ids
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.project_name}-redis"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.main.name
  security_group_ids   = [aws_security_group.redis.id]

  tags = {
    Name    = "${var.project_name}-redis"
    Project = var.project_name
  }
}
```

### Pattern 5: Lambda Stub with VPC Config (INFRA-01)
**What:** Placeholder Lambda function in VPC, pointing to a placeholder ECR image; replaced with real image in Phase 4
**When to use:** Phase 1 — establish resource existence and VPC wiring before application code is ready

```hcl
# Source: terraform-aws-modules/lambda examples + kindatechnical.com VPC guide

resource "aws_lambda_function" "predictor" {
  function_name = "${var.project_name}-predictor"
  role          = aws_iam_role.lambda.arn

  # Phase 1: stub image — replaced by CI/CD in Phase 7
  package_type = "Image"
  image_uri    = "${aws_ecr_repository.predictor.repository_url}:latest"

  architectures = ["x86_64"]  # NOT arm64 — ONNX Runtime ARM64 bug

  memory_size = 512
  timeout     = 60

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      REDIS_HOST   = aws_elasticache_cluster.redis.cache_nodes[0].address
      REDIS_PORT   = "6379"
      S3_BUCKET    = aws_s3_bucket.models.bucket
    }
  }
}
```

### Pattern 6: Docker Compose for Local Development (INFRA-04)
**What:** All development services in a single docker-compose.yml; mirrors production topology
**When to use:** Local development and CI integration testing

```yaml
# Source: Official Airflow docs (airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/)
# Adapted for this project's needs

version: '3.8'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: airflow
      POSTGRES_PASSWORD: airflow
      POSTGRES_DB: airflow
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes

  airflow-init:
    image: apache/airflow:3.1.8
    depends_on:
      - postgres
      - redis
    environment:
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@postgres/airflow
      AIRFLOW__CELERY__BROKER_URL: redis://redis:6379/0
      AIRFLOW__CELERY__RESULT_BACKEND: db+postgresql://airflow:airflow@postgres/airflow
    command: version
    # Run: docker compose run airflow-init airflow db migrate

  airflow-scheduler:
    image: apache/airflow:3.1.8
    depends_on:
      - postgres
      - redis
    environment:
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@postgres/airflow
      AIRFLOW__CELERY__BROKER_URL: redis://redis:6379/0
      AIRFLOW__CELERY__RESULT_BACKEND: db+postgresql://airflow:airflow@postgres/airflow
      AIRFLOW__CORE__EXECUTOR: SequentialExecutor  # matches t3.micro constraint
    volumes:
      - ./dags:/opt/airflow/dags
      - ./logs:/opt/airflow/logs
    command: scheduler

  airflow-api-server:
    image: apache/airflow:3.1.8
    depends_on:
      - postgres
    environment:
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@postgres/airflow
      AIRFLOW__CORE__EXECUTOR: SequentialExecutor
    ports:
      - "8080:8080"
    volumes:
      - ./dags:/opt/airflow/dags
      - ./logs:/opt/airflow/logs
    command: api-server

volumes:
  postgres_data:
```

### Anti-Patterns to Avoid
- **Creating any resource before the billing alarm:** Apply `modules/billing` separately first (`terraform apply -target=module.billing`), then apply the rest.
- **Using the console to create even one resource:** Console-created resources are invisible to Terraform state; `terraform destroy` will miss them, causing daily cost leakage.
- **Using `deletion_protection=true` or omitting `skip_final_snapshot=true` on RDS:** `terraform destroy` will hang or error, requiring manual console intervention at 11pm when you're trying to shut down.
- **Using ElastiCache Serverless instead of Provisioned:** Serverless ElastiCache is not free-tier eligible. Use `aws_elasticache_cluster` with `node_type = "cache.t3.micro"`, NOT `aws_elasticache_serverless`.
- **Using DynamoDB PAY_PER_REQUEST:** On-demand billing mode disqualifies the table from the always-free 25 WCU/25 RCU tier. Use PROVISIONED with 5/5 for Phase 1.
- **Putting Lambda VPC config in after initial apply:** Adding `vpc_config` to an existing Lambda function triggers a full replace (destroy + create). Design VPC config in from the start.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Billing alarm | Custom Lambda that polls Cost Explorer | `aws_cloudwatch_metric_alarm` on `EstimatedCharges` | Native CloudWatch metric, zero runtime cost, no polling |
| VPC networking | Manual security group rules without SG chaining | SG referencing SGs (e.g., Lambda SG allows egress to Redis SG) | Avoids IP-based rules that break when resources restart |
| Orphan detection | Custom resource tagging script | AWS CLI: `aws ec2 describe-snapshots --owner-ids self`, `aws ec2 describe-addresses` | CLI commands are instant and authoritative |
| Swap configuration | EBS swap partition (requires stop/start) | `fallocate` swap file in `user_data` | Swap file works on any EBS volume without repartitioning; survives instance restarts via fstab |
| Secrets management | Hardcoded DB passwords in terraform.tfvars | Terraform variables + `sensitive = true` + AWS Secrets Manager or environment variables | Prevents secrets in state file and git history |

**Key insight:** The entire Phase 1 is infrastructure primitives — every one of these problems has an AWS-native or Terraform-native solution. Nothing custom is warranted.

---

## Common Pitfalls

### Pitfall 1: Billing Metrics Only in us-east-1
**What goes wrong:** `aws_cloudwatch_metric_alarm` for `EstimatedCharges` applied in `us-west-2` or any non-us-east-1 region creates successfully but never enters ALARM state because billing metrics don't exist outside us-east-1.
**Why it happens:** AWS billing aggregation is global but the metric namespace `AWS/Billing` only publishes to CloudWatch in `us-east-1`.
**How to avoid:** Add a `provider "aws" { alias = "billing"; region = "us-east-1" }` block and reference it with `provider = aws.billing` on all billing alarm resources.
**Warning signs:** Alarm stays in "Insufficient data" state after spending accumulates.

### Pitfall 2: ElastiCache Free Tier Eligibility
**What goes wrong:** ElastiCache charges start immediately for AWS accounts created after July 15, 2025 — the free tier was restructured.
**Why it happens:** AWS changed the ElastiCache free tier terms in mid-2025.
**How to avoid:** Verify account creation date in AWS Console → Account → Account settings before Phase 1. If ineligible: (a) tear down ElastiCache immediately after Phase 1 verification, (b) use Feast SQLite online store locally (reduced fidelity), or (c) accept the ~$0.017/hr cost for the cache.t3.micro.
**Warning signs:** ElastiCache line item appears on the billing console immediately after creation.

### Pitfall 3: terraform destroy Hangs on RDS
**What goes wrong:** `terraform destroy` waits indefinitely for an RDS final snapshot to complete, or fails entirely if `deletion_protection=true`.
**Why it happens:** Default RDS settings require a final snapshot and have deletion protection enabled.
**How to avoid:** Set `skip_final_snapshot = true`, `deletion_protection = false`, and `backup_retention_period = 0` in the `aws_db_instance` resource from the start.
**Warning signs:** `terraform destroy` output shows RDS in "deleting" for more than 15 minutes.

### Pitfall 4: Lambda Stub Requires a Valid ECR Image to Apply
**What goes wrong:** `terraform apply` on the Lambda function fails because the ECR repository is empty — no image exists to reference.
**Why it happens:** `aws_lambda_function` with `package_type = "Image"` validates that the `image_uri` is resolvable at apply time.
**How to avoid:** Either (a) push a placeholder image to ECR before applying the Lambda resource, or (b) use a public placeholder image URI and switch to ECR in Phase 4. Option (a) is simpler: `docker pull public.ecr.aws/lambda/python:3.11 && docker tag ... && docker push <ecr_uri>:latest`.
**Warning signs:** `terraform apply` error: `InvalidParameterValueException: Source image ... does not exist`.

### Pitfall 5: VPC Subnet Configuration for ElastiCache + Lambda
**What goes wrong:** Lambda in VPC cannot reach ElastiCache because they are in different subnets or the security groups don't allow port 6379 traffic.
**Why it happens:** ElastiCache requires a subnet group in private subnets; Lambda must be in the same VPC; security group rules must explicitly allow Lambda SG → Redis SG on port 6379.
**How to avoid:** Create a shared VPC with both public (EC2/NAT) and private subnets (RDS, ElastiCache, Lambda). Lambda SG: outbound 6379 to Redis SG. Redis SG: inbound 6379 from Lambda SG. Use security group IDs (not CIDR) for both rules.
**Warning signs:** Lambda function times out on Redis connection with `Connection refused` or `timeout` in CloudWatch logs.

### Pitfall 6: User Data Changes Force EC2 Replacement
**What goes wrong:** Modifying `user_data` on an existing `aws_instance` triggers a destroy-then-create, resulting in a new instance with a different IP and lost state.
**Why it happens:** Terraform treats user_data changes as requiring instance replacement by default.
**How to avoid:** Get the user_data script right on the first apply. If iteration is needed during development, use `lifecycle { ignore_changes = [user_data] }` and apply user_data changes via SSM Run Command instead.
**Warning signs:** `terraform plan` shows `-/+` (replace) on the EC2 instance after any user_data edit.

### Pitfall 7: SNS Email Subscription Requires Manual Confirmation
**What goes wrong:** Billing alarm fires but no email is received because SNS email subscription was never confirmed.
**Why it happens:** SNS email subscriptions require the recipient to click a confirmation link. Terraform cannot automate this step.
**How to avoid:** After `terraform apply` on the billing module, immediately check email and confirm the SNS subscription. Add a `null_resource` with a `local-exec` that prints a reminder, or document this as a mandatory manual step in the spin_up.sh script.
**Warning signs:** SNS subscription shows `PendingConfirmation` status in AWS console.

---

## Code Examples

### Orphan Audit Script (INFRA-05)
```bash
#!/bin/bash
# Source: AWS CLI documentation + re:Post community patterns
# scripts/audit_orphans.sh — run after terraform destroy

set -e
REGION="${AWS_DEFAULT_REGION:-us-east-2}"
PROJECT="${PROJECT_NAME:-crypto-vol}"

echo "=== Auditing for orphaned AWS resources ==="

echo "--- EBS Snapshots ---"
aws ec2 describe-snapshots \
  --owner-ids self \
  --filters "Name=tag:Project,Values=${PROJECT}" \
  --query 'Snapshots[*].[SnapshotId,StartTime,VolumeSize]' \
  --output table \
  --region "${REGION}"

echo "--- Elastic IPs ---"
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp]' \
  --output table \
  --region "${REGION}"

echo "--- RDS Snapshots ---"
aws rds describe-db-snapshots \
  --snapshot-type manual \
  --query 'DBSnapshots[*].[DBSnapshotIdentifier,SnapshotCreateTime,Status]' \
  --output table \
  --region "${REGION}"

echo "--- Running EC2 Instances ---"
aws ec2 describe-instances \
  --filters "Name=instance-state-name,Values=running,stopped" \
             "Name=tag:Project,Values=${PROJECT}" \
  --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name]' \
  --output table \
  --region "${REGION}"

echo "=== Audit complete. If any resources listed above, delete them manually ==="
```

### DynamoDB Table (Provisioned for Free Tier)
```hcl
# Source: Terraform Registry aws_dynamodb_table + dynobase.dev free tier guide

resource "aws_dynamodb_table" "predictions" {
  name         = "${var.project_name}-predictions"
  billing_mode = "PROVISIONED"  # NOT PAY_PER_REQUEST — free tier applies to PROVISIONED only
  read_capacity  = 5
  write_capacity = 5

  hash_key  = "prediction_id"

  attribute {
    name = "prediction_id"
    type = "S"
  }

  # TTL to avoid unbounded storage growth
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name    = "${var.project_name}-predictions"
    Project = var.project_name
  }
}
```

### Security Group Chaining for Lambda → Redis
```hcl
# Source: kindatechnical.com VPC guide + AWS docs security group patterns

resource "aws_security_group" "redis" {
  name        = "${var.project_name}-redis-sg"
  description = "ElastiCache Redis security group"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]  # only Lambda can reach Redis
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "lambda" {
  name        = "${var.project_name}-lambda-sg"
  description = "Lambda function security group"
  vpc_id      = var.vpc_id

  egress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.redis.id]  # only to Redis
  }

  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # HTTPS for S3, W&B, etc.
  }
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| API Gateway REST API (v1) for Lambda | API Gateway HTTP API (v2) with `aws_apigatewayv2_api` | 2019 but fully mature by 2022 | 70% cost reduction; lower latency; simpler Terraform config for GET endpoints |
| ElastiCache Serverless (launched 2023) | ElastiCache Provisioned (`aws_elasticache_cluster`) | N/A — Serverless is NOT free-tier | For this project, Provisioned is correct because Serverless is billed per-use with no free tier |
| Airflow SequentialExecutor (single-file state) | Still correct for t3.micro | N/A | SequentialExecutor is appropriate for t3.micro memory constraints; CeleryExecutor requires Redis+workers and is overkill |
| Terraform 0.x `depends_on` workarounds | Explicit `depends_on` in resource blocks | Terraform 0.13+ | `depends_on` is first-class; use it to enforce billing alarm → other resources ordering |

**Deprecated/outdated:**
- `aws_api_gateway_rest_api` for new Lambda projects: Use `aws_apigatewayv2_api` (HTTP API) instead — same free tier, lower cost beyond free tier, simpler Terraform.
- `cache.t2.micro` for ElastiCache: t3.micro is the current smallest instance and is also free-tier eligible; t2.micro is legacy.
- Airflow LocalExecutor with SQLite: Explicitly unsupported for anything beyond developer laptop use; RDS PostgreSQL is required.

---

## Open Questions

1. **ElastiCache Free Tier Eligibility**
   - What we know: Free tier expired for accounts created after July 15, 2025 (verified via Amazon ElastiCache Pricing page)
   - What's unclear: User's AWS account creation date is unknown
   - Recommendation: Check account creation date before Phase 1 execution. If ineligible, either accept ~$0.42/day cost during active development hours only (torn down nightly), or switch Feast online store to SQLite local file (loses production fidelity but zero cost).

2. **Lambda Stub Bootstrap Image**
   - What we know: Lambda `package_type = "Image"` requires a valid ECR image at `terraform apply` time
   - What's unclear: Whether to use a public AWS base image as placeholder or build a minimal stub Docker image
   - Recommendation: Use `public.ecr.aws/lambda/python:3.11` as placeholder, push to private ECR before Lambda resource apply. Document this as a pre-apply step in spin_up.sh.

3. **Terraform State Storage**
   - What we know: Local state (`.terraform.tfstate`) is the simplest path; S3 remote state is more robust
   - What's unclear: Project requirements don't specify state backend
   - Recommendation: Use local state for Phase 1 (simplest). If the project is on GitHub, gitignore `*.tfstate` and `*.tfstate.backup`. Remote S3 backend can be added in Phase 7 (CI/CD).

---

## Sources

### Primary (HIGH confidence)
- HashiCorp Terraform Developer Docs — Standard Module Structure: https://developer.hashicorp.com/terraform/language/modules/develop/structure
- Airflow Official Docker Compose Docs (3.1.8): https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html
- AWS re:Post — ec2-memory-swap-file: https://repost.aws/knowledge-center/ec2-memory-swap-file
- AWS ElastiCache Pricing (free tier terms): https://aws.amazon.com/elasticache/pricing/
- DynamoDB Free Tier Guide (dynobase.dev): https://dynobase.dev/dynamodb-free-tier/

### Secondary (MEDIUM confidence)
- oneuptime.com 2026-02-23 — CloudWatch billing alarm Terraform HCL: https://oneuptime.com/blog/post/2026-02-23-how-to-create-cost-monitoring-alerts-with-terraform/view (verified billing metric in us-east-1 requirement against multiple sources)
- binbashar/terraform-aws-cost-billing-alarm GitHub + Terraform Registry — billing alarm module pattern: https://registry.terraform.io/modules/binbashar/cost-billing-alarm/aws/latest
- kindatechnical.com — Lambda VPC security group configuration: https://kindatechnical.com/aws-lambda/configuring-vpc-subnets-and-security-groups-for-lambda-functions.html
- ndench.github.io — terraform destroy RDS final snapshot issue: https://ndench.github.io/terraform/terraform-destroy-rds
- DEV Community — ElastiCache Redis Terraform: https://dev.to/giasuddin90/creating-an-aws-elasticache-redis-cluster-using-terraform-eb6

### Tertiary (LOW confidence)
- terraform-aws-modules/terraform-aws-elasticache README — subnet group pattern (GitHub, no specific date verified)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all Terraform resource types are official AWS provider resources; versions verified; free-tier limits confirmed from official AWS pricing pages
- Architecture: HIGH — Terraform module structure is from official HashiCorp docs; billing alarm pattern verified from two current (2026) sources
- Pitfalls: HIGH — all 7 pitfalls are either documented in official Terraform/AWS docs or in official GitHub issues on terraform-provider-aws

**Research date:** 2026-03-12
**Valid until:** 2026-06-12 (Terraform AWS provider stable; ElastiCache free tier policy change risk is the one area to recheck)
