output "ec2_public_ip" {
  description = "Public IP of the Airflow EC2 instance"
  value       = module.compute.ec2_public_ip
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (hostname:port)"
  value       = module.compute.rds_endpoint
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint hostname"
  value       = module.compute.redis_endpoint
}

output "s3_bucket_name" {
  description = "Name of the S3 data bucket"
  value       = module.storage.s3_bucket_name
}

output "ecr_repository_url" {
  description = "ECR repository URL for the predictor Lambda image"
  value       = module.storage.ecr_repository_url
}

output "api_gateway_url" {
  description = "API Gateway invoke URL for the predictor API"
  value       = module.serverless.api_gateway_url
}

output "dynamodb_table_name" {
  description = "DynamoDB table name for prediction logging"
  value       = module.storage.dynamodb_table_name
}

output "sns_billing_topic_arn" {
  description = "SNS topic ARN for billing alerts"
  value       = module.billing.sns_topic_arn
}

output "lambda_function_name" {
  description = "Lambda function name for the predictor"
  value       = module.serverless.lambda_function_name
}

output "sns_drift_topic_arn" {
  description = "SNS topic ARN for drift alerts"
  value       = module.serverless.sns_drift_topic_arn
}
