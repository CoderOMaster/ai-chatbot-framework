/*
Example Terraform snippet for deploying to AWS ECS Fargate. This is a minimal example and omits VPC/Subnet/ALB config.
You will need to adapt and integrate into your networking and IAM setup.
*/

provider "aws" {
  region = var.aws_region
}

resource "aws_ecs_cluster" "this" {
  name = "integration-service-cluster"
}

resource "aws_ecs_task_definition" "service" {
  family                   = "integration-service"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  container_definitions    = jsonencode([
    {
      name      = "integration-service"
      image     = var.container_image
      essential = true
      portMappings = [
        { containerPort = 8000, hostPort = 8000 }
      ]
      environment = [
        { name = "LOG_LEVEL", value = "info" },
        { name = "PORT", value = "8000" },
      ]
    }
  ])
}

resource "aws_ecs_service" "service" {
  name            = "integration-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.service.arn
  launch_type     = "FARGATE"
  desired_count   = 3
  network_configuration {
    subnets         = var.private_subnets
    security_groups = [var.service_security_group]
    assign_public_ip = false
  }
}

/* You must create aws_iam_role.ecs_task_execution with appropriate policies, and provide variables for image/subnets/security groups. */
