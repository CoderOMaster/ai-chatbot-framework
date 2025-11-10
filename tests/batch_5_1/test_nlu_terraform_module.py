import pathlib


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def test_nlu_terraform_module_resources_and_vars_and_dockerfiles():
    # Terraform module files
    main_tf = read("infra/terraform/nlu/main.tf")
    variables_tf = read("infra/terraform/nlu/variables.tf")

    # EFS filesystem for models, ECS task/service
    assert "aws_efs_file_system\" \"nlu_models" in main_tf
    assert "aws_ecs_task_definition\" \"nlu_runtime" in main_tf
    assert "aws_ecs_service\" \"nlu_runtime" in main_tf

    # Container exposes port 8001 and mounts /models
    assert "containerPort = 8001" in main_tf
    assert "sourceVolume = \"models\"" in main_tf
    assert "containerPath = \"/models\"" in main_tf

    # Env vars
    assert "MODEL_DIR" in main_tf
    assert "SPACY_LANG_MODEL" in main_tf

    # Variables
    for var in (
        "region",
        "cluster_arn",
        "execution_role_arn",
        "task_role_arn",
        "image",
        "cpu",
        "memory",
        "desired_count",
        "subnets",
        "security_groups",
        "assign_public_ip",
        "spacy_lang_model",
    ):
        assert f"variable \"{var}\"" in variables_tf

    # Docker artifacts exist
    assert pathlib.Path("ai-chatbot-framework/dockerfiles/Dockerfile.nlu").is_file()
    assert pathlib.Path("ai-chatbot-framework/dockerfiles/nlu-requirements.txt").is_file()
    assert pathlib.Path("ai-chatbot-framework/docker-compose.nlu.yml").is_file()

    # Requirements include FastAPI and Uvicorn
    req = read("ai-chatbot-framework/dockerfiles/nlu-requirements.txt")
    assert "fastapi" in req
    assert "uvicorn" in req
# Dockerfile content sanity
    dockerfile = read("ai-chatbot-framework/dockerfiles/Dockerfile.nlu")
    assert "EXPOSE 8001" in dockerfile
    assert "uvicorn" in dockerfile

    # docker-compose file content sanity
    compose = read("ai-chatbot-framework/docker-compose.nlu.yml")
    assert "nlu-runtime" in compose
    assert "nlu-trainer" in compose
    assert "8001:8001" in compose
    assert "MODEL_DIR=/models" in compose