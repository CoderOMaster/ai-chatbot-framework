/*
Example Terraform snippet for deploying to AWS ECS Fargate.
This is a simplified example; in production you must configure IAM roles, VPC, subnets, security groups, logging and secrets.
*/
provider "aws" {
  region = var.aws_region
}

resource "aws_ecr_repository" "chatlogs" {
  name = "chatlogs"
}

resource "aws_ecs_cluster" "chatlogs" {
  name = "chatlogs-cluster"
}

resource "aws_ecs_task_definition" "chatlogs" {
  family                   = "chatlogs-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "chatlogs"
      image     = "${aws_ecr_repository.chatlogs.repository_url}:latest"
      essential = true
      portMappings = [
        { containerPort = 8000, hostPort = 8000 }
      ]
      environment = [
        { name = "DB_DSN", value = var.db_dsn }
        { name = "LOG_LEVEL", value = "INFO" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = "/ecs/chatlogs"
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "chatlogs" {
  name            = "chatlogs-service"
  cluster         = aws_ecs_cluster.chatlogs.id
  task_definition = aws_ecs_task_definition.chatlogs.arn
  desired_count   = 3
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.private_subnets
    security_groups = [var.sg_id]
    assign_public_ip = false
  }

  depends_on = [aws_ecs_task_definition.chatlogs]
}

variable "aws_region" {}
variable "db_dsn" {}
variable "private_subnets" {
  type = list(string)
}
variable "sg_id" {}
