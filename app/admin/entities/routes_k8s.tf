/*
  Example Terraform for deploying as ECS Fargate Service.
  This is a minimal skeleton and should be adapted to your VPC, ALB, and IAM setup.
*/
provider "aws" {
  region = "us-east-1"
}

resource "aws_ecs_cluster" "this" {
  name = "entities-cluster"
}

resource "aws_iam_role" "task_execution" {
  name = "ecsTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_ecs_task_definition" "entities" {
  family                   = "entities-task"
  cpu                      = "512"
  memory                   = "1024"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "entities"
      image     = "<your-registry>/entities-service:latest"
      essential = true
      portMappings = [
        { containerPort = 8000, hostPort = 8000, protocol = "tcp" }
      ]
      environment = [
        { name = "DB_URL", value = "<your-db-connection-string>" },
        { name = "LOG_LEVEL", value = "INFO" }
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
    subnets         = ["<subnet-ids>"]
    security_groups = ["<sg-ids>"]
    assign_public_ip = true
  }
}
