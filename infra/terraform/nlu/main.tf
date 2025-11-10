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

resource "aws_efs_file_system" "nlu_models" {
  creation_token = "nlu-models"
  encrypted      = true
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
  tags = {
    Name = "nlu-models"
  }
}

resource "aws_ecs_task_definition" "nlu_runtime" {
  family                   = "nlu-runtime"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "nlu-runtime"
      image     = var.image
      essential = true
      portMappings = [{ containerPort = 8001, hostPort = 8001 }]
      environment = [
        { name = "MODEL_DIR", value = "/models" },
        { name = "SPACY_LANG_MODEL", value = var.spacy_lang_model }
      ]
      mountPoints = [
        { sourceVolume = "models", containerPath = "/models", readOnly = false }
      ]
    }
  ])

  volume {
    name = "models"
    efs_volume_configuration {
      file_system_id = aws_efs_file_system.nlu_models.id
      transit_encryption = "ENABLED"
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
    assign_public_ip = var.assign_public_ip
  }
}