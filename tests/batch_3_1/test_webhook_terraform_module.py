import pathlib


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def test_webhook_lambda_files_exist_and_requirements():
    # Ensure handlers exist
    assert pathlib.Path("lambda/handlers/webhooks/facebook.py").is_file()
    assert pathlib.Path("lambda/handlers/webhooks/rest.py").is_file()
    # Ensure aiohttp is declared for these handlers
    req = read("lambda/handlers/webhooks/requirements.txt")
    assert "aiohttp" in req


def test_webhook_terraform_module_resources_and_vars():
    main_tf = read("infra/terraform/webhook-lambdas/main.tf")
    variables_tf = read("infra/terraform/webhook-lambdas/variables.tf")
    outputs_tf = read("infra/terraform/webhook-lambdas/outputs.tf")

    # IAM Role and basic CW policy
    assert "aws_iam_role\" \"webhook_lambda_exec_role" in main_tf
    assert "AWSLambdaBasicExecutionRole" in main_tf

    # Lambda functions for facebook and rest
    assert "aws_lambda_function\" \"facebook_webhook" in main_tf
    assert "aws_lambda_function\" \"rest_webhook" in main_tf

    # Handlers point to expected module paths (packaging must provide these)
    assert "handler       = \"lambda_handlers.webhooks.facebook.handler\"" in main_tf
    assert "handler       = \"lambda_handlers.webhooks.rest.handler\"" in main_tf

    # Environment variables for forwarding and facebook secret
    assert "FACEBOOK_APP_SECRET" in main_tf
    assert "FORWARDING_ENDPOINT" in main_tf

    # API Gateway resources and methods for both endpoints
    assert "aws_api_gateway_rest_api\" \"webhooks" in main_tf
    assert "aws_api_gateway_resource\" \"facebook_path" in main_tf
    assert "aws_api_gateway_method\" \"facebook_post" in main_tf
    assert "aws_api_gateway_integration\" \"facebook_post" in main_tf
    assert "aws_api_gateway_resource\" \"rest_path" in main_tf
    assert "aws_api_gateway_method\" \"rest_post" in main_tf
    assert "aws_api_gateway_integration\" \"rest_post" in main_tf

    # Variables
    for var in (
        "region",
        "lambda_timeout",
        "lambda_memory",
        "api_gateway_stage",
        "forwarding_endpoint",
        "forwarding_sqs_url",
        "facebook_app_secret",
    ):
        assert f"variable \"{var}\"" in variables_tf

    # Outputs defined
    assert "output \"facebook_webhook_url\"" in outputs_tf
    assert "output \"rest_webhook_url\"" in outputs_tf
    assert "output \"lambda_arns\"" in outputs_tf