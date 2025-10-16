/*
 Example Terraform skeleton to deploy a container to AWS ECS Fargate.
 Fill in variables and adjust according to your infra patterns.
*/

provider "aws" {
  region = var.aws_region
}

resource "aws_ecs_cluster" "this" {
  name = "entity-store-cluster"
}

resource "aws_ecr_repository" "this" {
  name = "entity-store"
}

resource "aws_iam_role" "task_execution_role" {
  name = "ecsTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_execution_assume_role.json
}

data "aws_iam_policy_document" "ecs_task_execution_assume_role" {
  statement {
    effect = "Allow"
    principals {
      type = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role_policy_attachment" "task_exec_attach" {
  role       = aws_iam_role.task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_task_definition" "task" {
  family                   = "entity-store-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.task_execution_role.arn

  container_definitions = jsonencode([
    {
      name      = "entity-store"
      image     = "${aws_ecr_repository.this.repository_url}:latest"
      essential = true
      portMappings = [
        { containerPort = 8000, hostPort = 8000 }
      ]
      environment = [
        { name = "MONGODB_URI", value = var.mongodb_uri },
        { name = "MONGODB_DB", value = var.mongodb_db }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = "/ecs/entity-store"
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "service" {
  name            = "entity-store-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.task.arn
  desired_count   = 3
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.private_subnets
    security_groups = var.security_groups
    assign_public_ip = false
  }
}

variable "aws_region" {}
variable "mongodb_uri" {}
variable "mongodb_db" {}
variable "private_subnets" { type = list(string) }
variable "security_groups" { type = list(string) }
