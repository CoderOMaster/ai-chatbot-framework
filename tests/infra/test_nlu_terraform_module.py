from pathlib import Path
import re


def test_nlu_terraform_module_files_present():
    required = [
        "infra/terraform/nlu/main.tf",
        "infra/terraform/nlu/variables.tf",
        "infra/terraform/nlu/outputs.tf",
    ]
    for p in required:
        assert Path(p).exists(), f"missing {p}"


def test_main_tf_includes_efs_and_ecs_resources():
    content = Path("infra/terraform/nlu/main.tf").read_text()
    assert "aws_efs_file_system" in content
    assert "aws_ecs_task_definition" in content
    assert "aws_ecs_service" in content
    # Check env vars wiring
    assert "MODEL_DIR" in content or "MODELS_DIR" in content
    assert "SPACY_LANG_MODEL" in content


def test_variables_and_outputs_defined():
    vars_txt = Path("infra/terraform/nlu/variables.tf").read_text()
    outs_txt = Path("infra/terraform/nlu/outputs.tf").read_text()

    for v in [
        "region",
        "cluster_arn",
        "execution_role_arn",
        "task_role_arn",
        "runtime_image",
        "subnet_ids",
        "security_group_ids",
        "desired_count",
        "runtime_cpu",
        "runtime_memory",
        "spacy_model",
        "enable_efs",
    ]:
        assert re.search(fr"variable \"{v}\"", vars_txt)

    for o in ["efs_id", "ecs_task_definition_arn", "ecs_service_name"]:
        assert re.search(fr"output \"{o}\"", outs_txt)