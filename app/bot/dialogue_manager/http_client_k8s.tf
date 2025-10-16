/* Example ECS Fargate service (simplified). Adapt to your infra and providers. */
provider "aws" {
  region = var.region
}

resource "aws_ecs_cluster" "this" {
  name = "http-client-cluster"
}

resource "aws_ecs_task_definition" "http_client" {
  family                   = "http-client"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "http-client"
      image     = var.image
      portMappings = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }]
      essential = true
      environment = [
        { name = "SERVICE_PORT", value = "8000" },
        { name = "LOG_LEVEL", value = "INFO" }
      ]
    }
  ])
}

resource "aws_ecs_service" "http_client" {
  name            = "http-client-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.http_client.arn
  desired_count   = 3
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.subnets
    security_groups = var.security_groups
    assign_public_ip = false
  }
}

/* You will also need an ALB, target group, IAM roles, and other infra. This file is a starting point. */
