/* Example Terraform resources for deploying to ECS Fargate.
   This is a simplified example that requires an existing VPC and subnets.
   Replace placeholders and expand IAM roles and security groups for production. */

provider "aws" {
  region = var.aws_region
}

variable "aws_region" { default = "us-east-1" }
variable "vpc_id" {}
variable "subnet_ids" { type = list(string) }
variable "cluster_name" { default = "fastapi-cluster" }
variable "container_image" { default = "<registry>/fastapi-microservice:latest" }

resource "aws_ecs_cluster" "this" {
  name = var.cluster_name
}

resource "aws_iam_role" "task_exec_role" {
  name = "ecsTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    effect = "Allow"
    principals {
      type = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role_policy_attachment" "ecs_exec_policy" {
  role       = aws_iam_role.task_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/fastapi-microservice"
  retention_in_days = 14
}

resource "aws_ecs_task_definition" "this" {
  family                   = "fastapi-microservice"
  cpu                      = "512"
  memory                   = "1024"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.task_exec_role.arn

  container_definitions = jsonencode([
    {
      name      = "fastapi-microservice"
      image     = var.container_image
      cpu       = 512
      memory    = 1024
      essential = true
      portMappings = [ { containerPort = 8000, protocol = "tcp" } ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
      environment = [
        { name = "LOG_LEVEL", value = "INFO" },
      ]
    }
  ])
}

resource "aws_ecs_service" "this" {
  name            = "fastapi-microservice"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  launch_type     = "FARGATE"
  desired_count   = 3

  network_configuration {
    subnets         = var.subnet_ids
    assign_public_ip = false
    security_groups = ["<security-group-id>"]
  }
  depends_on = [aws_iam_role_policy_attachment.ecs_exec_policy]
}
