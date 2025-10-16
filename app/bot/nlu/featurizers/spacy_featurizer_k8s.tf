###############################
# Example Terraform skeleton (AWS EKS + Fargate)
# This is a simplified example. In production you should use the official aws/eks modules
###############################

provider "aws" {
  region = var.aws_region
}

# Create EKS cluster (minimal)
resource "aws_eks_cluster" "this" {
  name     = "spacy-featurizer-cluster"
  role_arn = aws_iam_role.eks[0].arn

  vpc_config {
    subnet_ids = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = false
  }

  depends_on = [aws_iam_role_policy_attachment.eks-AmazonEKSClusterPolicy]
}

# Create Fargate profile so pods in a namespace run on Fargate
resource "aws_eks_fargate_profile" "featurer" {
  cluster_name = aws_eks_cluster.this.name
  fargate_profile_name = "spacy-featurizer-profile"
  pod_execution_role_arn = aws_iam_role.fargate_pod.arn

  subnet_ids = var.private_subnet_ids

  selector {
    namespace = "spacy-featurizer"
  }
}

# Note: You'll need to create VPC, subnets, IAM roles and policies (omitted here for brevity).
# After TF creates the cluster, build and push Docker image to ECR and apply the Kubernetes manifests (kubectl / helm).
