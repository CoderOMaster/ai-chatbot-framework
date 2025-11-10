import pathlib


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def test_core_api_service_terraform_resources_and_vars():
    main_tf = read("infra/terraform/core-api-service/main.tf")
    variables_tf = read("infra/terraform/core-api-service/variables.tf")

    # ECS cluster, task def, service, security group, ALB, listener, target group
    assert "aws_ecs_cluster\" \"core" in main_tf
    assert "aws_ecs_task_definition\" \"core_api" in main_tf
    assert "aws_ecs_service\" \"core_api" in main_tf
    assert "aws_security_group\" \"svc" in main_tf
    assert "aws_lb\" \"this" in main_tf
    assert "aws_lb_listener\" \"http" in main_tf
    assert "aws_lb_target_group\" \"tg" in main_tf

    # Health check uses /ready
    assert "/ready" in main_tf

    # Environment variables include DB host/name and model forwarding endpoint
    assert "MONGODB_HOST" in main_tf
    assert "MONGODB_DATABASE" in main_tf
    assert "MODEL_FORWARDING_ENDPOINT" in main_tf

    # Variables
    for var in (
        "region",
        "image",
        "mongodb_host",
        "mongodb_database",
        "model_forwarding_endpoint",
        "task_cpu",
        "task_memory",
        "desired_count",
        "vpc_id",
        "public_subnet_ids",
        "private_subnet_ids",
    ):
        assert f"variable \"{var}\"" in variables_tf