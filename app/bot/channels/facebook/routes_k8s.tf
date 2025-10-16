/*
  Example Terraform snippets for deploying to ECS (Fargate) or EKS.
  This is illustrative: adapt to your organization standards, networking, IAM and VPC.
*/

/* ECS Fargate - minimal example */
provider "aws" {
  region = "us-east-1"
}

resource "aws_ecs_cluster" "this" {
  name = "facebook-webhook-cluster"
}

resource "aws_iam_role" "ecs_task_exec" {
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

resource "aws_ecs_task_definition" "facebook_webhook" {
  family                   = "facebook-webhook"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_exec.arn

  container_definitions = jsonencode([
    {
      name      = "facebook-webhook"
      image     = "<your-registry>/facebook-webhook:latest"
      essential = true
      portMappings = [ { containerPort = 8000, protocol = "tcp" } ]
      environment = [
        { name = "DATABASE_URL", value = var.database_url }
      ]
    }
  ])
}

/* EKS deployment is typically done with kubernetes provider applying the manifests in 'kubernetes_manifest' */
