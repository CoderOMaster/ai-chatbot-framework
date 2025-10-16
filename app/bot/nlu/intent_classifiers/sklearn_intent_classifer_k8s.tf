/*
  Example Terraform resources to deploy on ECS Fargate. This is a simplified
  example; in production you'd add networking (VPC, subnets), IAM roles, load
  balancer, autoscaling, and secrets management.
*/

provider "aws" {
  region = var.aws_region
}

variable "aws_region" { default = "us-east-1" }
variable "app_image" { description = "ECR image URI for the service" }
variable "cluster_name" { default = "sklearn-intent-cluster" }

resource "aws_ecs_cluster" "this" {
  name = var.cluster_name
}

resource "aws_iam_role" "task_execution_role" {
  name = "ecsTaskExecutionRole-sklearn"
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

resource "aws_iam_role_policy_attachment" "execution_policy" {
  role       = aws_iam_role.task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_task_definition" "task" {
  family                   = "sklearn-intent-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.task_execution_role.arn

  container_definitions = jsonencode([
    {
      name      = "sklearn-intent-container"
      image     = var.app_image
      cpu       = 256
      memory    = 512
      essential = true
      portMappings = [
        { containerPort = 8000, hostPort = 8000, protocol = "tcp" }
      ]
      environment = [
        { name = "MODEL_DIR", value = "/app/models" },
        { name = "MODEL_NAME", value = "sklearn_intent_model.hd5" }
      ]
    }
  ])
}

resource "aws_ecs_service" "service" {
  name            = "sklearn-intent-service"
  cluster         = aws_ecs_cluster.this.id
  desired_count   = 3
  launch_type     = "FARGATE"
  task_definition = aws_ecs_task_definition.task.arn

  network_configuration {
    subnets         = var.subnets
    security_groups = var.security_groups
    assign_public_ip = true
  }
}

/* Note: you must supply variables for subnets, security_groups, region and image.
   In real world usage, also add ALB or NLB to front the service, provide IAM
   secrets to pull model files from S3, and set up autoscaling. */
