variable "project_name" {
  type        = string
  description = "Project name prefix for all serverless resources"
}

variable "ecr_repository_url" {
  type        = string
  description = "ECR repository URL for the Lambda predictor image"
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "List of private subnet IDs for Lambda VPC config"
}

variable "lambda_sg_id" {
  type        = string
  description = "Security group ID for Lambda functions"
}

variable "redis_endpoint" {
  type        = string
  description = "ElastiCache Redis endpoint hostname"
}

variable "s3_bucket_name" {
  type        = string
  description = "S3 bucket name for model artifacts"
}

variable "s3_bucket_arn" {
  type        = string
  description = "S3 bucket ARN for IAM policy"
}

variable "dynamodb_table_arn" {
  type        = string
  description = "DynamoDB table ARN for IAM policy"
}
