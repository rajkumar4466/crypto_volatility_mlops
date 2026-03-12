variable "aws_region" {
  type        = string
  default     = "us-east-2"
  description = "AWS region for all resources (except billing alarm which is always us-east-1)"
}

variable "project_name" {
  type        = string
  default     = "crypto-vol"
  description = "Project name prefix for all resources"
}

variable "alert_email" {
  type        = string
  description = "Email address to receive billing and drift alerts"
}

variable "db_username" {
  type        = string
  default     = "airflow"
  description = "RDS PostgreSQL master username"
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "RDS PostgreSQL master password"
}

variable "ec2_key_name" {
  type        = string
  description = "Name of the EC2 key pair for SSH access to the Airflow instance"
}
