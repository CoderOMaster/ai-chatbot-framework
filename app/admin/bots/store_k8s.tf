/*
  Example Terraform snippet (high-level) for deploying container to ECS (Fargate) or EKS.
  This is a simplified example and will require additional resources (VPC, IAM roles, ECR, etc.).
*/

/* EKS (using aws_eks_node_group etc.) - high level */

provider "aws" {
  region = var.region
}

resource "aws_eks_cluster" "this" {
  name     = "bot-store-cluster"
  role_arn = aws_iam_role.eks_cluster.arn
  vpc_config {
    subnet_ids = var.private_subnets
  }
}

# ... node groups, security groups etc.

/* ECS (Fargate) example - high level */
resource "aws_ecs_cluster" "bot_store" {
  name = "bot-store-cluster"
}

resource "aws_ecs_task_definition" "bot_store_task" {
  family                   = "bot-store"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  container_definitions    = jsonencode([
    {
      name      = "bot-store"
      image     = "${var.ecr_repo_url}:latest"
      essential = true
      portMappings = [ { containerPort = 8000, hostPort = 8000 } ]
      environment = [
        { name = "DB_URL", value = var.db_url },
        { name = "DB_NAME", value = var.db_name }
      ]
    }
  ])
}

resource "aws_ecs_service" "bot_store_service" {
  name            = "bot-store"
  cluster         = aws_ecs_cluster.bot_store.id
  task_definition = aws_ecs_task_definition.bot_store_task.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.private_subnets
    security_groups = [aws_security_group.ecs_sg.id]
    assign_public_ip = false
  }
}
