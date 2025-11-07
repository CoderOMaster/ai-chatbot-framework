terraform {
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

# Optional EFS for model artifacts
resource "aws_efs_file_system" "nlu_models" {
  creation_token = "nlu-models"
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
}

# Task definition for nlu-runtime
resource "aws_ecs_task_definition" "nlu_runtime" {
  family                   = "nlu-runtime"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.runtime_cpu
  memory                   = var.runtime_memory
  network_mode             = "awsvpc"
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "nlu-runtime"
      image     = var.runtime_image
      essential = true
      portMappings = [
        { containerPort = 8001, hostPort = 8001, protocol = "tcp" }
      ]
      environment = [
        { name = "MODEL_DIR", value = "/models" },
        { name = "SPACY_LANG_MODEL", value = var.spacy_model }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = "/ecs/nlu-runtime"
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
      mountPoints = var.enable_efs ? [
        { sourceVolume = "models", containerPath = "/models", readOnly = false }
      ] : []
    }
  ])

  dynamic "volume" {
    for_each = var.enable_efs ? [1] : []
    content {
      name = "models"
      efs_volume_configuration {
        file_system_id = aws_efs_file_system.nlu_models.id
      }
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
    subnets         = var.subnet_ids
    security_groups = var.security_group_ids
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}