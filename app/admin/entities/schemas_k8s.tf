/*
Example Terraform for deploying to ECS Fargate. This is a simplified snippet; integrate into your infra modules.
You need to supply variables for AWS provider, VPC, subnets, security groups, and ECR repository/image.
*/

provider "aws" {
  region = var.aws_region
}

resource "aws_ecr_repository" "entities" {
  name = "entities-service"
}

resource "aws_ecs_cluster" "this" {
  name = "entities-cluster"
}

resource "aws_ecs_task_definition" "entities" {
  family                   = "entities-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "entities-service"
      image     = "${aws_ecr_repository.entities.repository_url}:latest"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "MONGO_URI", value = var.mongo_uri },
        { name = "MONGO_DB", value = var.mongo_db }
      ]
    }
  ])
}

resource "aws_ecs_service" "entities" {
  name            = "entities-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.entities.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.subnet_ids
    security_groups = [var.security_group_id]
    assign_public_ip = false
  }
}
