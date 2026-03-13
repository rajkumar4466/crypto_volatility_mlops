variable "aws_region" {
  type        = string
  description = "AWS region for CloudWatch resources"
}

variable "project_name" {
  type        = string
  default     = "crypto-vol"
  description = "Project name prefix for all resources"
}

variable "alert_email" {
  type        = string
  description = "Email address to receive ML monitoring alerts (drift + accuracy)"
}

variable "cloudwatch_namespace" {
  type        = string
  default     = "CryptoVolatility/Monitoring"
  description = "CloudWatch metric namespace used by the monitoring Python code"
}
