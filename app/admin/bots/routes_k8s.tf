/*
  Example Terraform snippet to deploy to ECS Fargate.
  This is illustrative and will need AWS provider configuration, IAM roles, and subnets set up.
*/

provider "aws" {
  region = var.region
}

variable "region" {
  default = "us-east-1"
}

variable "cluster_name" {
  default = "bots-cluster"
}

resource "aws_ecs_cluster" "this" {
  name = var.cluster_name
}

resource "aws_ecs_task_definition" "bots_task" {
  family                   = "bots-service"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "bots-service",
      image     = "<your-registry>/bots-service:latest",
      essential = true,
      portMappings = [{
        containerPort = 8000,
        hostPort      = 8000,
        protocol      = "tcp"
      }],
      environment = [
        {name = "PORT", value = "8000"},
        {name = "LOG_LEVEL", value = "INFO"}
      ]
    }
  ])
}

# Service, target group, ALB, and other resources would be created and wired to this task definition.
