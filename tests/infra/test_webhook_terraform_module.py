from pathlib import Path


def test_webhook_terraform_files_exist_and_contain_resources():
    root = Path("infra/terraform/webhook-lambdas")
    assert (root / "main.tf").exists()
    assert (root / "variables.tf").exists()
    assert (root / "outputs.tf").exists()

    content = (root / "main.tf").read_text()
    assert "aws_lambda_function" in content
    assert "facebook_webhook" in content
    assert "rest_webhook" in content
    assert "aws_api_gateway_rest_api" in content