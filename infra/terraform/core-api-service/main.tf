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

# ECS Cluster
resource "aws_ecs_cluster" "core" {
  name = "core-api-cluster"
}

# IAM Role for task execution
resource "aws_iam_role" "task_execution" {
  name               = "core-api-task-exec-role"
  assume_role_policy = data.aws_iam_policy_document.task_assume_role.json
}

data "aws_iam_policy_document" "task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "ecr_pull" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Task definition
resource "aws_ecs_task_definition" "core_api" {
  family                   = "core-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "core-api"
      image     = var.image
      essential = true
      portMappings = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }]
      environment = [
        { name = "MONGODB_HOST", value = var.mongodb_host },
        { name = "MONGODB_DATABASE", value = var.mongodb_database },
        { name = "MODEL_FORWARDING_ENDPOINT", value = var.model_forwarding_endpoint }
      ]
      logConfiguration = {
        logDriver = "awslogs",
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

# Security group for service
resource "aws_security_group" "svc" {
  name        = "core-api-sg"
  description = "Allow HTTP"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ALB
resource "aws_lb" "this" {
  name               = "core-api-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.svc.id]
  subnets            = var.public_subnet_ids
}

resource "aws_lb_target_group" "tg" {
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
    matcher             = "200-399"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.tg.arn
  }
}

# ECS Service
resource "aws_ecs_service" "core_api" {
  name            = "core-api"
  cluster         = aws_ecs_cluster.core.id
  task_definition = aws_ecs_task_definition.core_api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.svc.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.tg.arn
    container_name   = "core-api"
    container_port   = 8000
  }
}