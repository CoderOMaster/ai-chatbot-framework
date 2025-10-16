/* Example Terraform configuration sketch for deploying to AWS ECS Fargate with ECR */

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  default = "us-east-1"
}

resource "aws_ecr_repository" "spacy_featurizer" {
  name = "spacy-featurizer"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name = "ecsTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
}

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_ecs_cluster" "cluster" {
  name = "spacy-featurizer-cluster"
}

# Task, service, and associated IAM policies are omitted for brevity — this is a scaffold.
# You will create aws_ecs_task_definition, aws_ecs_service, and required iam policies and roles.

/* For EKS: consider using the official EKS module (terraform-aws-modules/eks/aws) and deploy the Kubernetes manifest via kubectl/helm CI step. */
