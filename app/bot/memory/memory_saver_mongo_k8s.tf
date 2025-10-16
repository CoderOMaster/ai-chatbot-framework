# NOTE: These are example snippets. Customize for your infra (VPC, subnets, IAM, etc.).

# Example: ECS Fargate skeleton
provider "aws" {
  region = var.aws_region
}

resource "aws_ecr_repository" "memory_saver" {
  name = "memory-saver-mongo"
}

# Create IAM task execution role and policy (omitted full policies here)
resource "aws_iam_role" "ecs_task_execution" {
  name = "ecsTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

# Define ECS cluster
resource "aws_ecs_cluster" "cluster" {
  name = "memory-saver-cluster"
}

# Task definition for Fargate
resource "aws_ecs_task_definition" "task" {
  family                   = "memory-saver-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  container_definitions    = jsonencode([
    {
      name = "memory-saver-mongo"
      image = "${aws_ecr_repository.memory_saver.repository_url}:latest"
      essential = true
      portMappings = [
        { containerPort = 8000, hostPort = 8000 }
      ]
      environment = [
        { name = "MONGODB_URI", value = var.mongodb_uri },
        { name = "DB_NAME", value = "chatbot" },
        { name = "COLLECTION_NAME", value = "state" }
      ]
    }
  ])
}

# Service and ALB setup are omitted — follow standard ECS Fargate patterns

# Example: EKS cluster provisioning requires more resources (VPC, subnets, node groups). Use EKS module:
# module "eks" {
#   source  = "terraform-aws-modules/eks/aws"
#   cluster_name = "my-eks-cluster"
#   ...
# }

# After creating EKS, apply the Kubernetes manifest shown earlier, or use the kubernetes provider in Terraform to apply Deployment and Service.
