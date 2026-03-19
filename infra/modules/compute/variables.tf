variable "project_name" {
  type        = string
  description = "Project name prefix for all compute resources"
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "List of public subnet IDs (EC2 placed in first)"
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "List of private subnet IDs (RDS and ElastiCache)"
}

variable "airflow_sg_id" {
  type        = string
  description = "Security group ID for the Airflow EC2 instance"
}

variable "rds_sg_id" {
  type        = string
  description = "Security group ID for RDS"
}

variable "redis_sg_id" {
  type        = string
  description = "Security group ID for ElastiCache Redis"
}

variable "key_name" {
  type        = string
  description = "EC2 key pair name for SSH access"
}

variable "db_username" {
  type        = string
  description = "RDS PostgreSQL master username"
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "RDS PostgreSQL master password"
}

variable "s3_bucket_name" {
  type        = string
  description = "S3 bucket name for IAM policy"
}

variable "dynamodb_table_name" {
  type        = string
  description = "DynamoDB table name for IAM policy"
}

variable "aws_region" {
  type        = string
  description = "AWS region for scoping IAM policies"
}
