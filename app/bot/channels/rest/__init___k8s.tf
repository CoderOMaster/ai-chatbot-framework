/* Example Terraform for deploying image to ECS Fargate (skeleton). Replace variables and expand for your infra.
   This is a minimal example: create ECR, an ECS task definition and Fargate service behind an ALB.
   For a production setup you need VPC, subnets, security groups, IAM roles, and more. */

provider "aws" {
  region = var.aws_region
}

variable "aws_region" { default = "us-east-1" }
variable "cluster_name" { default = "microservice-cluster" }
variable "service_name" { default = "microservice-service" }
variable "image_uri" { description = "ECR image URI with tag" }

resource "aws_ecr_repository" "repo" {
  name = "microservice"
}

resource "aws_ecs_cluster" "cluster" {
  name = var.cluster_name
}

# Task execution and task role policies are required — omitted for brevity
# Create an ECS Task Definition (Fargate)
resource "aws_ecs_task_definition" "task" {
  family                   = "${var.service_name}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "microservice"
      image     = var.image_uri
      essential = true
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "DB_POOL_MIN", value = "1" },
        { name = "DB_POOL_MAX", value = "10" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = "/ecs/${var.service_name}"
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

# Create ECS Service (fronted by an ALB is recommended; omitted for brevity)
resource "aws_ecs_service" "service" {
  name            = var.service_name
  cluster         = aws_ecs_cluster.cluster.id
  launch_type     = "FARGATE"
  task_definition = aws_ecs_task_definition.task.arn
  desired_count   = 3
  network_configuration {
    subnets         = var.private_subnets
    security_groups = var.security_groups
    assign_public_ip = false
  }
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
}

# NOTE: This is a skeleton. You must add IAM roles (ecs_task_execution role), ALB, target group and listener configuration,
# VPC / subnets / security groups, secrets manager integration for DATABASE_URL, and other production concerns.
