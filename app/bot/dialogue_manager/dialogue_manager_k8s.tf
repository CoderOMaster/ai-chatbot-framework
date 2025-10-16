# This is a skeleton Terraform module for deploying to EKS or ECS.
# Use this as a starting point and adapt to your infra.

# Example: create an ECS Fargate service
provider "aws" {
  region = var.aws_region
}

# ECR repo for images
resource "aws_ecr_repository" "dialogue_manager" {
  name = "dialogue-manager"
}

# ECS Task Definition (Fargate)
resource "aws_ecs_task_definition" "dialogue_manager" {
  family                   = "dialogue-manager"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "dialogue-manager",
      image     = "${aws_ecr_repository.dialogue_manager.repository_url}:latest",
      essential = true,
      portMappings = [
        { containerPort = 8000, hostPort = 8000 }
      ],
      environment = [
        { name = "MONGO_URI", value = var.mongo_uri },
        { name = "LOG_LEVEL", value = "INFO" }
      ]
    }
  ])
}

# ECS Service and LB should be defined here

# NOTE: This is only a minimal skeleton. For production, configure
# VPC, subnets, security groups, IAM roles for task execution, ALB, autoscaling, and logging.
