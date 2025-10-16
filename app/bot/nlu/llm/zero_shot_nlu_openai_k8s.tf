/*
  Example Terraform snippet for deploying to ECS Fargate.
  This is a skeleton to get started; you'll need to provide VPC, Subnets,
  and IAM roles according to your environment and security requirements.
*/
provider "aws" {
  region = var.aws_region
}

resource "aws_ecs_cluster" "this" {
  name = "zero-shot-nlu-cluster"
}

resource "aws_ecs_task_definition" "nlu_task" {
  family                   = "zero-shot-nlu"
  cpu                      = "512"
  memory                   = "1024"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "zero-shot-nlu",
      image     = var.image, # e.g. your-account.dkr.ecr.region.amazonaws.com/zero-shot-nlu:latest
      essential = true,
      portMappings = [{ containerPort = 8000, hostPort = 8000 }],
      environment = [
        { name = "OPENAI_BASE_URL", value = var.openai_base_url },
        { name = "OPENAI_API_KEY", value = var.openai_api_key },
      ],
      logConfiguration = {
        logDriver = "awslogs",
        options = {
          awslogs-group         = "/ecs/zero-shot-nlu",
          awslogs-region        = var.aws_region,
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "nlu_service" {
  name            = "zero-shot-nlu-svc"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.nlu_task.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.subnet_ids
    security_groups = var.security_group_ids
    assign_public_ip = false
  }
}
