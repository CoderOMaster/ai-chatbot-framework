import os
import re


def read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def test_core_api_terraform_resources_present():
    base = 'infra/terraform/core-api-service'
    assert os.path.exists(os.path.join(base, 'main.tf'))
    assert os.path.exists(os.path.join(base, 'variables.tf'))
    assert os.path.exists(os.path.join(base, 'outputs.tf'))

    main = read(os.path.join(base, 'main.tf'))
    # ECS cluster, task, service, ALB, target group, listener
    assert 'aws_ecs_cluster' in main
    assert 'aws_ecs_task_definition' in main
    assert 'aws_ecs_service' in main
    assert 'aws_lb' in main
    assert 'aws_lb_target_group' in main
    assert 'aws_lb_listener' in main

    # Health check uses /ready by default
    assert 'health_check' in main
    assert 'healthcheck_path' in main

    # Environment variables wired
    assert 'MONGODB_HOST' in main
    assert 'MONGODB_DATABASE' in main
    assert 'MODEL_FORWARDING_ENDPOINT' in main


def test_core_api_terraform_variables_and_outputs():
    base = 'infra/terraform/core-api-service'
    variables = read(os.path.join(base, 'variables.tf'))
    outputs = read(os.path.join(base, 'outputs.tf'))

    for v in [
        'region','name','cluster_name','image','vpc_id','public_subnet_ids','private_subnet_ids',
        'alb_sg_id','service_sg_id','mongodb_host','mongodb_database','model_forwarding_endpoint',
        'healthcheck_path','task_cpu','task_memory','desired_count']:
        assert f'variable "{v}"' in variables

    for o in ['alb_dns_name','service_name','cluster_id']:
        assert f'output "{o}"' in outputs