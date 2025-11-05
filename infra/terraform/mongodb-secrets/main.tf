terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

resource "aws_secretsmanager_secret" "mongodb_credentials" {
  name = "${var.secret_name_prefix}/credentials"
  description = "Credentials for MongoDB used by ai-chatbot-framework"
}

resource "aws_secretsmanager_secret_version" "mongodb_credentials_version" {
  secret_id     = aws_secretsmanager_secret.mongodb_credentials.id
  secret_string = jsonencode({
    host     = var.mongodb_host
    port     = var.mongodb_port
    username = var.mongodb_username
    password = var.mongodb_password
    database = var.mongodb_database
  })
}