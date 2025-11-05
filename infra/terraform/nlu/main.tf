// Terraform placeholders for NLU ECS and EFS resources
terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

// Placeholder: ECS task definition and service for nlu-runtime
resource "aws_ecs_task_definition" "nlu_runtime" {
  family                   = "nlu-runtime"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "4096"
  network_mode             = "awsvpc"
  container_definitions    = jsonencode([
    {
      name      = "nlu-runtime"
      image     = var.nlu_image
      essential = true
      portMappings = [{containerPort = 8001, hostPort = 8001}]
      mountPoints = [{sourceVolume = "models", containerPath = "/models"}]
    }
  ])
  volume {
    name = "models"
    efs_volume_configuration {
      file_system_id = aws_efs_file_system.models.id
    }
  }
}

resource "aws_efs_file_system" "models" {
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
}