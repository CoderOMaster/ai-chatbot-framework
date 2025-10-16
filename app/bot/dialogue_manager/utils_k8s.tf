/*
Example Terraform config using the community module to create EKS with Fargate profiles.
This is a simplified example; for production you must configure VPC, IAM roles, and security properly.
*/

provider "aws" {
  region = var.aws_region
}

module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  cluster_name    = var.cluster_name
  cluster_version = "1.26"
  subnets         = var.private_subnets
  vpc_id          = var.vpc_id

  # Enable Fargate; pods in specified namespaces will be scheduled on Fargate.
  fargate_profile = {
    enabled = true
  }

  node_groups = {}

  tags = {
    Terraform   = "true"
    Environment = var.environment
  }
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "kubeconfig" {
  value = module.eks.kubeconfig
}

# variables.tf (example values)
# variable "aws_region" { default = "us-east-1" }
# variable "cluster_name" { default = "ai-chatbot-cluster" }
# variable "vpc_id" {}
# variable "private_subnets" { type = list(string) }
# variable "environment" { default = "dev" }

/* Notes:
 - You can also deploy to ECS Fargate by creating an ECS cluster, task definition, and service.
 - The Terraform snippet uses a module; ensure you read the module docs for required inputs (VPC, subnets, IAM).
*/
