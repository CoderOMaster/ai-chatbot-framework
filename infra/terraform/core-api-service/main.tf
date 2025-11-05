terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "aws_ecs_cluster" "core_api_cluster" {
  name = "core-api-cluster"
}

# Task definition and service would go here. This file serves as a placeholder
# with notes referenced by the batch plan. Implementers should add full task
# definition, IAM roles, ALB, target groups and listener rules, and secrets
# references to Secrets Manager as needed for their environment.

output "cluster_name" {
  value = aws_ecs_cluster.core_api_cluster.name
}