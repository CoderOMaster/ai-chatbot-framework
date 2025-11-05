from pathlib import Path


def test_terraform_contains_efs_and_task_definition():
    p = Path("infra/terraform/nlu/main.tf")
    assert p.exists()
    txt = p.read_text()
    assert "aws_efs_file_system" in txt
    assert "aws_ecs_task_definition" in txt