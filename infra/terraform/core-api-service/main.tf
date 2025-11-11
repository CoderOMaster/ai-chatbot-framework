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

resource "aws_ecs_cluster" "core" {
  name = "core-api-cluster"
}

resource "aws_iam_role" "task_exec" {
  name               = "core-api-task-exec-role"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
}

data "aws_iam_policy_document" "task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_ecs_task_definition" "core" {
  family                   = "core-api-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.task_exec.arn

  container_definitions = jsonencode([
    {
      name      = "core-api"
      image     = var.image
      essential = true
      portMappings = [{ containerPort = 8000, hostPort = 8000 }]
      environment = [
        { name = "MONGODB_HOST", value = var.mongodb_host },
        { name = "MONGODB_DATABASE", value = var.mongodb_database },
        { name = "MODEL_FORWARDING_ENDPOINT", value = var.model_forwarding_endpoint },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = "/ecs/core-api"
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/ready || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 10
      }
    }
  ])
}

resource "aws_lb" "core" {
  name               = "core-api-alb"
  internal           = false
  load_balancer_type = "application"
  subnets            = var.public_subnets
  security_groups    = [var.alb_sg]
}

resource "aws_lb_target_group" "core" {
  name     = "core-api-tg"
  port     = 8000
  protocol = "HTTP"
  vpc_id   = var.vpc_id
  health_check {
    path                = "/ready"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.core.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.core.arn
  }
}

resource "aws_ecs_service" "core" {
  name            = "core-api-service"
  cluster         = aws_ecs_cluster.core.id
  task_definition = aws_ecs_task_definition.core.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.private_subnets
    security_groups = [var.service_sg]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.core.arn
    container_name   = "core-api"
    container_port   = 8000
  }
}

variable "region" { type = string }
variable "image" { type = string }
variable "mongodb_host" { type = string }
variable "mongodb_database" { type = string }
variable "model_forwarding_endpoint" { type = string }
variable "vpc_id" { type = string }
variable "public_subnets" { type = list(string) }
variable "private_subnets" { type = list(string) }
variable "alb_sg" { type = string }
variable "service_sg" { type = string }
variable "desired_count" { type = number, default = 2 }