Below are two concise Terraform examples you can adapt: one for EKS (Kubernetes) and a short ECS Fargate alternative.

--- EKS (using AWS EKS module) ---
# providers.tf
provider "aws" {
  region = var.aws_region
}

# main.tf (abridged)
module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  cluster_name    = var.cluster_name
  cluster_version = "1.27"
  subnets         = var.private_subnets
  vpc_id          = var.vpc_id

  node_groups = {
    default = {
      desired_capacity = 3
      max_capacity     = 5
      min_capacity     = 3
      instance_type    = "t3.medium"
    }
  }
}

# After EKS cluster created, use kubectl provider to apply the Kubernetes manifest or use helm to deploy.

--- ECS Fargate (short example) ---
provider "aws" {
  region = var.aws_region
}

resource "aws_ecs_cluster" "cluster" {
  name = "example-cluster"
}

resource "aws_ecs_task_definition" "task" {
  family                   = "example-service"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  container_definitions    = jsonencode([
    {
      name      = "example-service"
      image     = "<REGISTRY>/example-service:latest"
      essential = true
      portMappings = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }]
      environment = [
        { name = "DATABASE_URL", value = "${var.database_url}" }
      ]
    }
  ])
}

resource "aws_ecs_service" "service" {
  name            = "example-service"
  cluster         = aws_ecs_cluster.cluster.id
  task_definition = aws_ecs_task_definition.task.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.private_subnets
    assign_public_ip = false
    security_groups = [aws_security_group.ecs_sg.id]
  }
}

# Note: Both examples are templates. Provide IAM roles, security groups, subnets, and secrets handling
# (e.g., SSM Parameter Store or Secrets Manager) in production. Use a remote state backend (S3 + DynamoDB) and
# lock provider. Use terraform modules for repeated patterns.
