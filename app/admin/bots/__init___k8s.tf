## Terraform snippets for two deployment targets: EKS (Kubernetes) and ECS (Fargate).

# === ECS Fargate (AWS) - minimal example ===
# This is a simplified example. You must configure aws provider and IAM roles separately.

# Example (main.tf)
# provider "aws" { region = "us-east-1" }
# resource "aws_ecs_cluster" "this" { name = "service-cluster" }
# resource "aws_ecs_task_definition" "service" {
#   family = "service-task"
#   network_mode = "awsvpc"
#   requires_compatibilities = ["FARGATE"]
#   cpu = "512"
#   memory = "1024"
#   execution_role_arn = aws_iam_role.ecs_task_execution.arn
#   container_definitions = jsonencode([
#     {
#       name = "service",
#       image = "REPLACE_WITH_IMAGE:latest",
#       essential = true,
#       portMappings = [{ containerPort = 8000, hostPort = 8000 }],
#       environment = [
#         { name = "DATABASE_URL", value = "REPLACE" }
#       ]
#     }
#   ])
# }
# resource "aws_ecs_service" "service" {
#   name = "service"
#   cluster = aws_ecs_cluster.this.id
#   task_definition = aws_ecs_task_definition.service.arn
#   desired_count = 3
#   launch_type = "FARGATE"
#   network_configuration {
#     subnets = ["subnet-xxxxx"]
#     security_groups = ["sg-xxxxx"]
#     assign_public_ip = true
#   }
# }

# === EKS (Kubernetes) - minimal example ===
# Use the official EKS module or eksctl to create an EKS cluster, then `kubectl apply` the k8s manifest above.
# Example using terraform-aws-eks module (very abbreviated):
# module "eks" {
#   source          = "terraform-aws-modules/eks/aws"
#   cluster_name    = "example-cluster"
#   cluster_version = "1.27"
#   subnets         = ["subnet-...", "subnet-..."]
#   vpc_id          = "vpc-..."
#   worker_groups_launch_template = []
# }

# After creating cluster, configure kubectl and apply the Kubernetes manifest defined earlier.
