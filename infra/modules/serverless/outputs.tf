output "lambda_function_name" {
  description = "Lambda function name for the predictor"
  value       = aws_lambda_function.predictor.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.predictor.arn
}

output "api_gateway_url" {
  description = "API Gateway HTTP API invoke URL"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "sns_drift_topic_arn" {
  description = "SNS topic ARN for drift alerts"
  value       = aws_sns_topic.drift_alerts.arn
}

output "backfill_lambda_function_name" {
  description = "Backfill Lambda function name"
  value       = aws_lambda_function.backfill.function_name
}
