/*
Example Terraform snippets. These are skeletons and must be filled with organization-specific configuration.
1) EKS cluster (using aws provider and terraform-aws-eks module is recommended in production)
*/

# providers.tf
provider "aws" {
  region = var.aws_region
}

# eks-cluster.tf (very minimal example — prefer using community module)
resource "aws_eks_cluster" "eks" {
  name     = "integrations-eks-cluster"
  role_arn = aws_iam_role.eks_role.arn

  vpc_config {
    subnet_ids = var.private_subnet_ids
  }
}

# ecr repository for container images
resource "aws_ecr_repository" "integrations" {
  name = "integrations-service"
}

/*
Alternatively, a short ECS/Fargate example to run same image as a service:
*/

# ecs-example.tf (high-level sketch)
resource "aws_ecs_cluster" "cluster" {
  name = "integrations-cluster"
}

resource "aws_ecs_task_definition" "task" {
  family                   = "integrations-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "integrations"
      image     = "${aws_ecr_repository.integrations.repository_url}:latest"
      essential = true
      portMappings = [
        { containerPort = 8000, hostPort = 8000, protocol = "tcp" }
      ]
      environment = [
        { name = "DB_DSN", value = var.db_dsn }
      ]
    }
  ])
}

resource "aws_ecs_service" "service" {
  name            = "integrations-service"
  cluster         = aws_ecs_cluster.cluster.id
  task_definition = aws_ecs_task_definition.task.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.private_subnet_ids
    assign_public_ip = false
    security_groups  = [var.sg_id]
  }
}
