terraform {
  required_version = ">= 1.5.0"
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

resource "aws_efs_file_system" "nlu_models" {
  creation_token = "nlu-models"
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
}

# Placeholder ECS task definition for nlu-runtime
resource "aws_ecs_task_definition" "nlu_runtime" {
  family                   = "nlu-runtime"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.runtime_cpu
  memory                   = var.runtime_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "nlu-runtime"
      image     = var.image
      essential = true
      portMappings = [{ containerPort = 8001, hostPort = 8001 }]
      environment = [
        { name = "MODEL_DIR", value = var.model_dir },
        { name = "SPACY_LANG_MODEL", value = var.spacy_model }
      ]
      mountPoints = [
        {
          sourceVolume  = "models",
          containerPath = var.model_dir,
          readOnly      = true
        }
      ]
    }
  ])

  volume {
    name = "models"
    efs_volume_configuration {
      file_system_id = aws_efs_file_system.nlu_models.id
    }
  }
}

resource "aws_ecs_service" "nlu_runtime" {
  name            = "nlu-runtime"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.nlu_runtime.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.subnets
    security_groups = var.security_groups
    assign_public_ip = false
  }
}