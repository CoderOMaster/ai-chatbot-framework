/*
  Example: basic ECS Fargate service + task definition snippets
  This is illustrative — not a drop-in production-ready module.
*/

provider "aws" {
  region = var.region
}

# ECR repository
resource "aws_ecr_repository" "chatlog" {
  name = "chatlog-service"
}

# Task definition (partial)
resource "aws_ecs_task_definition" "chatlog_task" {
  family                   = "chatlog-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "chatlog-service"
      image     = "${aws_ecr_repository.chatlog.repository_url}:latest"
      essential = true
      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]
      environment = [
        { name = "MONGODB_URI", value = var.mongodb_uri },
        { name = "MONGODB_DB", value  = "chatbot" },
        { name = "MONGODB_COLLECTION", value = "state" }
      ]
    }
  ])
}

resource "aws_ecs_service" "chatlog_service" {
  name            = "chatlog-service"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.chatlog_task.arn
  desired_count   = 3
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.subnets
    security_groups = var.security_groups
    assign_public_ip = false
  }
}
