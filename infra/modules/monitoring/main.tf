# Monitoring module — CloudWatch dashboard, SNS ML alerts, and CloudWatch alarms
# This module is independent of the serverless drift-alerts SNS topic.
# The serverless module handles Python-level drift detection notifications;
# this module handles CloudWatch metric threshold alarms (accuracy + drift_score).

# ---------------------------------------------------------------------------
# SNS topic for ML monitoring alerts (separate from billing and drift-alerts)
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "ml_alerts" {
  name = "${var.project_name}-ml-alerts"

  tags = {
    Name    = "${var.project_name}-ml-alerts"
    Project = var.project_name
  }
}

resource "aws_sns_topic_subscription" "ml_alerts_email" {
  topic_arn = aws_sns_topic.ml_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---------------------------------------------------------------------------
# CloudWatch alarm: model rolling accuracy below 55% for 2 consecutive periods
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "accuracy_low" {
  alarm_name          = "${var.project_name}-rolling-accuracy-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "rolling_accuracy"
  namespace           = var.cloudwatch_namespace
  period              = 300
  statistic           = "Average"
  threshold           = 0.55
  alarm_description   = "Model rolling accuracy dropped below 55% for 2 consecutive 5-min periods"
  alarm_actions       = [aws_sns_topic.ml_alerts.arn]
  ok_actions          = [aws_sns_topic.ml_alerts.arn]
  treat_missing_data  = "notBreaching"
}

# ---------------------------------------------------------------------------
# CloudWatch alarm: feature drift score > 0.15 (= 2 of 12 features drifted)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "drift_detected" {
  alarm_name          = "${var.project_name}-feature-drift-detected"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "drift_score"
  namespace           = var.cloudwatch_namespace
  period              = 300
  statistic           = "Maximum"
  threshold           = 0.15
  alarm_description   = "Feature drift score exceeded 0.15 (2+ of 12 features drifted)"
  alarm_actions       = [aws_sns_topic.ml_alerts.arn]
  treat_missing_data  = "notBreaching"
}

# ---------------------------------------------------------------------------
# CloudWatch dashboard — 5 widgets (2 rows × layout over 24-unit grid)
# Row 1 (y=0): rolling_accuracy (w=12), drift_score (w=12)
# Row 2 (y=6): model_version (w=8), prediction_latency (w=8), retrain_count (w=8)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "mlops_monitoring" {
  dashboard_name = "${var.project_name}-monitoring"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [[var.cloudwatch_namespace, "rolling_accuracy"]]
          period  = 300
          stat    = "Average"
          region  = var.aws_region
          title   = "Rolling Model Accuracy (target: >= 0.55)"
          view    = "timeSeries"
          yAxis   = { left = { min = 0, max = 1 } }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [[var.cloudwatch_namespace, "drift_score"]]
          period  = 300
          stat    = "Maximum"
          region  = var.aws_region
          title   = "Feature Drift Score (alert: > 0.15)"
          view    = "timeSeries"
          yAxis   = { left = { min = 0, max = 1 } }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          metrics = [[var.cloudwatch_namespace, "model_version"]]
          period  = 300
          stat    = "Maximum"
          region  = var.aws_region
          title   = "Model Version (integer)"
          view    = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          metrics = [[var.cloudwatch_namespace, "prediction_latency"]]
          period  = 300
          stat    = "Average"
          region  = var.aws_region
          title   = "Prediction Latency (ms)"
          view    = "timeSeries"
          yAxis   = { left = { min = 0 } }
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 6
        width  = 8
        height = 6
        properties = {
          metrics = [[var.cloudwatch_namespace, "retrain_count"]]
          period  = 300
          stat    = "Sum"
          region  = var.aws_region
          title   = "Retrain Count"
          view    = "timeSeries"
          yAxis   = { left = { min = 0 } }
        }
      }
    ]
  })
}
