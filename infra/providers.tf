terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

# Default provider — deployment region (us-east-2)
provider "aws" {
  region = var.aws_region
}

# Billing provider alias — AWS billing metrics ONLY exist in us-east-1
provider "aws" {
  alias  = "billing"
  region = "us-east-1"
}
