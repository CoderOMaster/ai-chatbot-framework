from pathlib import Path

COMPOSE = Path("ai-chatbot-framework/docker-compose.nlu.yml")
TF_MAIN = Path("infra/terraform/nlu/main.tf")
TF_VARS = Path("infra/terraform/nlu/variables.tf")


def test_compose_file_and_services():
    assert COMPOSE.exists(), "docker-compose.nlu.yml should exist"
    src = COMPOSE.read_text(encoding="utf-8")

    # Ensure both services defined
    assert "nlu-runtime:" in src
    assert "nlu-trainer:" in src

    # Ensure volumes and env configuration are present
    assert "/mnt/models:/models" in src
    assert "MODEL_DIR=/models" in src
    assert "SPACY_LANG_MODEL=xx_core_web_sm" in src


def test_terraform_files_exist():
    assert TF_MAIN.exists(), "Terraform main.tf should exist for nlu"
    assert TF_VARS.exists(), "Terraform variables.tf should exist for nlu"


def test_terraform_resources_and_variables():
    main_src = TF_MAIN.read_text(encoding="utf-8")
    vars_src = TF_VARS.read_text(encoding="utf-8")

    # Provider and versions
    assert "required_providers" in main_src and "hashicorp/aws" in main_src
    assert 'provider "aws"' in main_src

    # EFS for models and ECS task/service
    assert 'resource "aws_efs_file_system" "nlu_models"' in main_src
    assert 'resource "aws_ecs_task_definition" "nlu_runtime"' in main_src
    assert 'resource "aws_ecs_service" "nlu_runtime"' in main_src
    assert 'containerPort = 8001' in main_src

    # Variables typical for ECS
    for v in [
        'variable "region"',
        'variable "cluster_arn"',
        'variable "execution_role_arn"',
        'variable "task_role_arn"',
        'variable "subnets"',
        'variable "security_groups"',
        'variable "image"',
    ]:
        assert v in vars_src

    assert 'variable "model_dir"' in vars_src
    assert 'variable "spacy_model"' in vars_src