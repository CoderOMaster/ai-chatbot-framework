### Minimal ECS Fargate (AWS) snippet (Terraform HCL v0.13+)
# This is a small sample to deploy the container to ECS Fargate. It omits many details (VPC, ALB, IAM roles)
# Fill in variables and resource ARNs for a production-ready configuration.

provider "aws" {
  region = var.aws_region
}

resource "aws_ecs_task_definition" "intent_task" {
  family                   = "intent-service"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "intent-service"
      image     = var.container_image
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "MONGO_URI", value = var.mongo_uri },
        { name = "MONGO_DB", value = var.mongo_db }
      ]
    }
  ])
}

resource "aws_ecs_service" "intent_service" {
  name            = "intent-service"
  cluster         = var.ecs_cluster_id
  launch_type     = "FARGATE"
  task_definition = aws_ecs_task_definition.intent_task.arn
  desired_count   = 3
  network_configuration {
    subnets         = var.subnets
    security_groups = var.security_groups
    assign_public_ip = false
  }
}

# Note: For EKS you'd instead apply the Kubernetes manifests or create a helm chart.
