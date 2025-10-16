############################################
# Example Terraform snippet to deploy to ECS (Fargate)
# This is a simplified example and omits IAM, VPC, subnet and security group setup.
############################################
provider "aws" {
  region = var.aws_region
}

resource "aws_ecs_cluster" "this" {
  name = "dialogue-manager-cluster"
}

resource "aws_ecs_task_definition" "task" {
  family                   = "dialogue-manager"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "dialogue-manager",
      image     = var.image, # e.g. your-registry/dialogue-manager:latest
      essential = true,
      portMappings = [
        { containerPort = 8000, hostPort = 8000 }
      ],
      environment = [
        { name = "DATABASE_URL", value = var.database_url },
        { name = "REDIS_URL", value = var.redis_url },
        { name = "LOG_LEVEL", value = "INFO" }
      ]
    }
  ])
}

resource "aws_ecs_service" "service" {
  name            = "dialogue-manager-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.task.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.subnets
    security_groups = var.security_groups
    assign_public_ip = false
  }
}

# Note: Add ALB, IAM roles, and proper security (IAM task role, execution role) in production.
