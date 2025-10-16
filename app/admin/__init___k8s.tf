/*
 Example Terraform snippets (skeletons) for two approaches: EKS (Kubernetes) and ECS (Fargate).
 These are illustrative and will require provider configuration, state and IAM roles.
*/

/* 1) EKS (create cluster) - Minimal skeleton */
provider "aws" {
  region = var.region
}

module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  cluster_name    = var.cluster_name
  cluster_version = "1.27"
  subnets         = var.subnets
  vpc_id          = var.vpc_id
  node_groups = {
    eks_nodes = {
      desired_capacity = 2
      instance_type    = "t3.medium"
    }
  }
}

/* Then push the docker image to ECR and apply the Kubernetes manifest using kubectl or helm. */

/* 2) ECS Fargate (skeleton) */
resource "aws_ecs_cluster" "this" {
  name = var.ecs_cluster_name
}

resource "aws_ecs_task_definition" "app" {
  family                   = "example-microservice"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "example-microservice"
      image     = "${var.ecr_repo_url}:latest"
      essential = true
      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]
      environment = [
        { name = "DB_URL", value = var.db_url }
      ]
    }
  ])
}

resource "aws_ecs_service" "service" {
  name            = "example-microservice"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.subnets
    security_groups = var.security_groups
    assign_public_ip = false
  }
}
