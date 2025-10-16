/* Minimal ECS Fargate service example (high-level skeleton). Replace variables and add IAM/network resources accordingly. */

provider "aws" {
  region = var.region
}

resource "aws_ecs_cluster" "this" {
  name = "messenger-adapter-cluster"
}

resource "aws_ecs_task_definition" "app" {
  family                   = "messenger-adapter"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "messenger-adapter",
      image     = var.image,
      essential = true,
      portMappings = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }],
      environment = [
        { name = "PAGE_ACCESS_TOKEN", value = var.page_access_token },
        { name = "APP_SECRET", value = var.app_secret },
        { name = "VERIFY_TOKEN", value = var.verify_token },
        { name = "DB_DSN", value = var.db_dsn }
      ]
    }
  ])
}

resource "aws_ecs_service" "service" {
  name            = "messenger-adapter-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.subnets
    security_groups = [var.security_group]
    assign_public_ip = false
  }
}
