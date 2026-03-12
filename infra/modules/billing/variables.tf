variable "project_name" {
  type        = string
  description = "Project name prefix for all billing resources"
}

variable "alert_email" {
  type        = string
  description = "Email address to subscribe to billing alerts"
}
