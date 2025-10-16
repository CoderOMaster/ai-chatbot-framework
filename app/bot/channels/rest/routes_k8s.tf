/* Example Terraform: create an ECS Fargate service or EKS cluster is large; here's a minimal ECS Fargate module sketch */

provider "aws" {
  region = var.aws_region
}

# ECR repo
resource "aws_ecr_repository" "dialogue_service" {
  name = "dialogue-service"
}

# IAM, Task Definition, Service, Cluster would follow; for production use the AWS ECS module or EKS module

# For EKS, use the official eks module: https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/latest

/* Note: full Terraform manifests exceed the scope here. Use existing modules for EKS/ECS and wire in the image from ECR, task role, and target group for ALB. */
