/*
  Example Terraform (AWS ECS Fargate) - skeleton
  Fill variables with appropriate values and credentials.
*/
provider "aws" {
  region = var.aws_region
}

variable "aws_region" { default = "us-east-1" }
variable "cluster_name" { default = "nlp-microservice-cluster" }
variable "service_name" { default = "nlp-microservice" }
variable "container_image" { default = "<YOUR_REGISTRY>/nlp-microservice:latest" }

resource "aws_ecs_cluster" "this" {
  name = var.cluster_name
}

resource "aws_iam_role" "task_execution" {
  name = "ecsTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_policy" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_task_definition" "task" {
  family                   = var.service_name
  cpu                      = "512"
  memory                   = "1024"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name      = var.service_name
      image     = var.container_image
      essential = true
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "APP_ENV" , value = "production" },
        # Add DB_URL as a secret or env var as needed
      ]
    }
  ])
}

# Create an ECS service behind an ALB (left as an exercise); this is a starting point.
