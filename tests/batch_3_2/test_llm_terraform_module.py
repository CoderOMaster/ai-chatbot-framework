import pathlib


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def test_llm_lambda_and_layer_and_vars():
    main_tf = read("infra/terraform/llm-lambdas/main.tf")
    variables_tf = read("infra/terraform/llm-lambdas/variables.tf")

    # Layer is defined and wired to function
    assert "aws_lambda_layer_version\" \"llm_client_layer" in main_tf
    assert "layers = [" in main_tf
    assert "llm-client-layer" in main_tf

    # IAM role and basic execution policy
    assert "aws_iam_role\" \"zero_shot_llm_role" in main_tf
    assert "AWSLambdaBasicExecutionRole" in main_tf

    # Lambda function name and handler
    assert "aws_lambda_function\" \"zero_shot_llm" in main_tf
    assert "handler       = \"lambda_handlers.llm.zero_shot.handler\"" in main_tf
    assert "python3.11" in main_tf

    # Environment variables
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL_NAME", "RETRY_ATTEMPTS", "PROMPT_DIR"):
        assert var in main_tf

    # Variables available with defaults or sensitive
    assert 'variable "region"' in variables_tf
    assert 'variable "lambda_timeout"' in variables_tf
    assert 'variable "lambda_memory"' in variables_tf
    assert 'variable "llm_base_url"' in variables_tf
    assert 'variable "llm_api_key"' in variables_tf
    assert 'sensitive   = true' in variables_tf
    assert 'variable "llm_model_name"' in variables_tf
    assert 'variable "retry_attempts"' in variables_tf
    assert 'variable "prompt_dir"' in variables_tf

    # Output defined
    assert 'output "zero_shot_llm_function_name"' in main_tf