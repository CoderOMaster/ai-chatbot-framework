This file provides two example snippets: one for EKS (cluster & nodegroup) and one for ECS (Fargate service). These are simplified and meant to be integrated into your infrastructure modules.

# Example: EKS (high-level)
provider "aws" {
  region = var.aws_region
}

module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  cluster_name    = var.cluster_name
  cluster_version = "1.26"
  subnets         = var.private_subnets
  vpc_id          = var.vpc_id
  node_groups = {
    primary = {
      desired_capacity = 2
      max_capacity     = 3
      min_capacity     = 1
      instance_type    = "t3.medium"
    }
  }
}

# After creating the cluster, deploy the Kubernetes manifest (e.g., via kubectl provider or CI/CD pipeline).

# Example: ECS Fargate (service & task)
resource "aws_ecs_cluster" "this" {
  name = "intent-service-cluster"
}

resource "aws_ecr_repository" "this" {
  name = "intent-service"
}

resource "aws_iam_role" "ecs_task_role" {
  name = "ecsTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

resource "aws_ecs_task_definition" "intent_task" {
  family                   = "intent-service"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  execution_role_arn = aws_iam_role.ecs_task_role.arn
  container_definitions = jsonencode([
    {
      name      = "intent-service"
      image     = "${aws_ecr_repository.this.repository_url}:latest"
      essential = true
      portMappings = [
        { containerPort = 8000, hostPort = 8000 }
      ]
      environment = [
        { name = "MONGO_URI", value = var.mongo_uri }
        { name = "DB_NAME", value = "app_db" }
      ]
    }
  ])
}

resource "aws_ecs_service" "intent_svc" {
  name            = "intent-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.intent_task.arn
  desired_count   = 3
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.private_subnets
    security_groups = [var.security_group_id]
    assign_public_ip = false
  }
}
