# Billing module — ALL resources use provider = aws.billing (us-east-1)
# AWS billing metrics (EstimatedCharges) are ONLY published in us-east-1
# This module must be applied FIRST, before any billable resource is created

terraform {
  required_providers {
    aws = {
      source                = "hashicorp/aws"
      version               = "~> 5.0"
      configuration_aliases = [aws.billing]
    }
  }
}

# SNS topic for billing alerts (in us-east-1)
resource "aws_sns_topic" "billing_alerts" {
  provider = aws.billing
  name     = "${var.project_name}-billing-alerts"

  tags = {
    Name    = "${var.project_name}-billing-alerts"
    Project = var.project_name
  }
}

# Email subscription — requires manual confirmation via email link
resource "aws_sns_topic_subscription" "billing_email" {
  provider  = aws.billing
  topic_arn = aws_sns_topic.billing_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# CloudWatch billing alarm — fires when estimated charges exceed $1
resource "aws_cloudwatch_metric_alarm" "billing_1_dollar" {
  provider = aws.billing

  alarm_name          = "${var.project_name}-billing-1-usd"
  alarm_description   = "AWS estimated charges exceeded $1 — crypto-vol project"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 21600 # 6 hours — AWS billing metric update frequency
  statistic           = "Maximum"
  threshold           = 1.0
  treat_missing_data  = "notBreaching"

  dimensions = {
    Currency = "USD"
  }

  alarm_actions = [aws_sns_topic.billing_alerts.arn]

  tags = {
    Name    = "${var.project_name}-billing-alarm"
    Project = var.project_name
  }
}
