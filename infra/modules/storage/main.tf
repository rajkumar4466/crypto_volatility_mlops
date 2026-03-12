# Storage module — S3 bucket, ECR repository, DynamoDB table
# All resources are "always-free" tier and persist across compute spin-up/tear-down cycles

# Random suffix to ensure globally unique S3 bucket name
resource "random_id" "suffix" {
  byte_length = 4
}

# S3 Bucket — Feast offline store, model artifacts, raw crypto data
resource "aws_s3_bucket" "data" {
  bucket        = "${var.project_name}-data-${random_id.suffix.hex}"
  force_destroy = true # Allow destroy even when bucket contains objects

  tags = {
    Name    = "${var.project_name}-data"
    Project = var.project_name
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ECR Repository — Lambda predictor container images
resource "aws_ecr_repository" "predictor" {
  name                 = "${var.project_name}-predictor"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # Allow destroy when images exist

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name    = "${var.project_name}-predictor"
    Project = var.project_name
  }
}

# DynamoDB Table — Prediction logging
# PROVISIONED billing mode required for always-free 25 WCU/25 RCU tier
resource "aws_dynamodb_table" "predictions" {
  name           = "${var.project_name}-predictions"
  billing_mode   = "PROVISIONED"
  read_capacity  = 5
  write_capacity = 5

  hash_key = "prediction_id"

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
