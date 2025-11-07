terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  secret_name = "${var.secret_name_prefix}/credentials"
}

resource "aws_secretsmanager_secret" "mongodb_credentials" {
  name        = local.secret_name
  description = "MongoDB credentials for AI Chatbot Framework"
}

resource "aws_secretsmanager_secret_version" "mongodb_credentials_version" {
  secret_id     = aws_secretsmanager_secret.mongodb_credentials.id
  secret_string = jsonencode({
    host     = "mongodb://" # override via TF var or CI pipeline
    port     = 27017
    username = ""
    password = ""
    database = "ai-chatbot-framework"
  })
}

output "secrets_arn" {
  value       = aws_secretsmanager_secret.mongodb_credentials.arn
  description = "ARN of the MongoDB credentials secret"
}