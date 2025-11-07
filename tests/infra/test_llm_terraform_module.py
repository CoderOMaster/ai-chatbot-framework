from pathlib import Path


def test_llm_terraform_files_exist_and_have_expected_content():
    root = Path('infra/terraform/llm-lambdas')
    assert (root / 'main.tf').exists()
    assert (root / 'variables.tf').exists()
    assert (root / 'outputs.tf').exists()

    main = (root / 'main.tf').read_text()
    assert 'aws_lambda_function' in main
    assert 'aws_lambda_layer_version' in main
    assert 'handler = "lambda_handlers.llm.zero_shot.handler"' in main
    # Ensure environment variables wired
    assert 'LLM_BASE_URL' in main and 'LLM_API_KEY' in main and 'LLM_MODEL_NAME' in main

    vars_tf = (root / 'variables.tf').read_text()
    assert 'variable "region"' in vars_tf
    assert 'variable "lambda_role_arn"' in vars_tf
    assert 'variable "llm_base_url"' in vars_tf
    assert 'variable "llm_api_key"' in vars_tf
    assert 'variable "llm_model_name"' in vars_tf

    outs = (root / 'outputs.tf').read_text()
    assert 'zero_shot_llm_function_name' in outs
    assert 'llm_client_layer_arn' in outs