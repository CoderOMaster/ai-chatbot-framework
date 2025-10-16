/*
This is a starting point for deploying to ECS (Fargate) or EKS. Adjust modules and providers.
Example: ECS Fargate service (very minimal). You must configure AWS provider, networking, IAM, and ECR.
*/

# Example ECS (Fargate) resource snippet (not complete, intended as a template)
provider "aws" {
  region = var.aws_region
}

resource "aws_ecs_cluster" "this" {
  name = "state-service-cluster"
}

resource "aws_ecs_task_definition" "this" {
  family                   = "state-service-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  container_definitions    = jsonencode([
    {
      name      = "state-service",
      image     = var.image_uri,
      essential = true,
      portMappings = [{ containerPort = 8000, hostPort = 8000 }],
      environment = [
        { name = "DB_URL", value = var.db_url },
        { name = "LOG_LEVEL", value = "INFO" }
      ]
    }
  ])
}

resource "aws_ecs_service" "this" {
  name            = "state-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.subnet_ids
    security_groups = [var.security_group_id]
    assign_public_ip = false
  }
}

# Note: For EKS, prefer deploying the Kubernetes manifest (provided above) to the cluster using kubeconfig.
