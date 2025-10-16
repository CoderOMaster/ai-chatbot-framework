## Example Terraform snippets (high level) for ECS (Fargate) and EKS

# 1) ECS / Fargate (AWS)
# - Assumes you have an ECR image pushed and existing VPC/Subnets/SG.

resource "aws_ecs_cluster" "this" {
  name = "integrations-cluster"
}

resource "aws_iam_role" "task_execution" {
  name = "ecsTaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_execution_assume_role.json
}

# task definition
resource "aws_ecs_task_definition" "this" {
  family                   = "integrations"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "integrations-service"
      image     = "<account>.dkr.ecr.<region>.amazonaws.com/integrations-service:latest"
      essential = true
      portMappings = [{ containerPort = 8000, hostPort = 8000 }]
      environment = [
        { name = "MONGODB_URI", value = "mongodb://mongo:27017" },
        { name = "MONGODB_DB", value = "appdb" }
      ]
    }
  ])
}

# service (attach to ALB or use service discovery)
resource "aws_ecs_service" "this" {
  name            = "integrations-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.private_subnets
    security_groups = [var.sg_id]
    assign_public_ip = false
  }
}


# 2) EKS (brief)
# - Use EKS module to provision cluster, then apply Kubernetes manifest shown earlier.
# Terraform for EKS is usually the official AWS EKS module; after cluster is created, use kubernetes provider to deploy the manifest.

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"
  # ... cluster configuration omitted for brevity
}

# After cluster, use kubernetes provider to apply the deployment/service above
