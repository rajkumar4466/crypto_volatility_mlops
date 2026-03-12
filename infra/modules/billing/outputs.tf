output "sns_topic_arn" {
  description = "ARN of the billing alerts SNS topic"
  value       = aws_sns_topic.billing_alerts.arn
}
