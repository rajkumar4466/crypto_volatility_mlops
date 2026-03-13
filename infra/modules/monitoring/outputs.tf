output "sns_topic_arn" {
  value       = aws_sns_topic.ml_alerts.arn
  description = "SNS topic ARN for ML monitoring alerts — use as SNS_TOPIC_ARN env var"
}

output "dashboard_url" {
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.mlops_monitoring.dashboard_name}"
  description = "CloudWatch dashboard URL"
}
