output "s3_bucket_name" {
  description = "Name of the S3 data bucket"
  value       = aws_s3_bucket.data.bucket
}

output "s3_bucket_arn" {
  description = "ARN of the S3 data bucket"
  value       = aws_s3_bucket.data.arn
}

output "ecr_repository_url" {
  description = "ECR repository URL (without tag) for the predictor Lambda image"
  value       = aws_ecr_repository.predictor.repository_url
}

output "ecr_repository_arn" {
  description = "ARN of the ECR predictor repository"
  value       = aws_ecr_repository.predictor.arn
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB predictions table"
  value       = aws_dynamodb_table.predictions.name
}

output "dynamodb_table_arn" {
  description = "ARN of the DynamoDB predictions table"
  value       = aws_dynamodb_table.predictions.arn
}
