# Compute module — EC2 (Airflow), RDS PostgreSQL, ElastiCache Redis
# BILLABLE resources — spin up/tear down daily

# Find latest Amazon Linux 2023 AMI
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# EC2 — Airflow host (t3.micro with 4GB swap)
resource "aws_instance" "airflow" {
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = "t3.micro"
  subnet_id              = var.public_subnet_ids[0]
  vpc_security_group_ids = [var.airflow_sg_id]
  key_name               = var.key_name

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  # Swap FIRST, then Docker — required per STATE.md INFRA-02 decision
  user_data = <<-EOF
    #!/bin/bash
    set -e

    # Step 1: Configure 4GB swap BEFORE any software installs
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    swapon --show

    # Step 2: System update
    dnf update -y

    # Step 3: Install Docker (Amazon Linux 2023 uses dnf, NOT yum or amazon-linux-extras)
    dnf install -y docker
    systemctl start docker
    systemctl enable docker
    usermod -a -G docker ec2-user
  EOF

  tags = {
    Name    = "${var.project_name}-airflow"
    Project = var.project_name
  }
}

# RDS Subnet Group
resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnet"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name    = "${var.project_name}-db-subnet"
    Project = var.project_name
  }
}

# RDS PostgreSQL 16 — Airflow metadata store
resource "aws_db_instance" "airflow_metadata" {
  identifier        = "${var.project_name}-airflow-db"
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = "db.t3.micro"
  allocated_storage = 20

  db_name  = "airflow"
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.rds_sg_id]

  # CRITICAL: allows terraform destroy without manual snapshot intervention
  skip_final_snapshot     = true
  deletion_protection     = false
  backup_retention_period = 0
  multi_az                = false

  tags = {
    Name    = "${var.project_name}-airflow-db"
    Project = var.project_name
  }
}

# ElastiCache Subnet Group
resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project_name}-redis-subnet"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name    = "${var.project_name}-redis-subnet"
    Project = var.project_name
  }
}

# ElastiCache Redis — Feast online store
resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.project_name}-redis"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.main.name
  security_group_ids   = [var.redis_sg_id]

  tags = {
    Name    = "${var.project_name}-redis"
    Project = var.project_name
  }
}
