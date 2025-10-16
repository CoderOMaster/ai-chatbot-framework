/*
Minimal Terraform sketch for deploying to ECS Fargate. This is a simplified example — fill in your VPC, subnets, and IAM roles.
*/

provider "aws" {
  region = "us-west-2"
}

resource "aws_ecs_cluster" "intents" {
  name = "intents-cluster"
}

resource "aws_ecs_task_definition" "intents_task" {
  family                   = "intents-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_exec.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "intents-service",
      image     = "<ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/intents-service:latest",
      essential = true,
      portMappings = [
        { containerPort = 8000, hostPort = 8000 }
      ],
      environment = [
        { name = "DB_URL", value = "${var.db_url}" },
        { name = "POOL_MIN", value = "1" },
        { name = "POOL_MAX", value = "10" }
      ]
    }
  ])
}

resource "aws_ecs_service" "intents_service" {
  name            = "intents-service"
  cluster         = aws_ecs_cluster.intents.id
  task_definition = aws_ecs_task_definition.intents_task.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.subnet_ids
    security_groups = [var.security_group_id]
    assign_public_ip = false
  }
}

# IAM roles, ECR repository, ALB, autoscaling, and other resources are omitted for brevity.
