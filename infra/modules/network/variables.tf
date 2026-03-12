variable "project_name" {
  type        = string
  description = "Project name prefix for all network resources"
}

variable "aws_region" {
  type        = string
  description = "AWS region — used to derive AZ names"
}
