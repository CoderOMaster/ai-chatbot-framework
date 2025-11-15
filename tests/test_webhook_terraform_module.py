def test_webhook_terraform_module_resources():
    with open("infra/terraform/webhook-lambdas/main.tf", "r", encoding="utf-8") as f:
        main_tf = f.read()

    # Validate IAM role, two lambda functions, API gateway resources, permissions, and deployment
    assert 'resource "aws_iam_role" "webhook_lambda_exec_role"' in main_tf
    assert 'resource "aws_lambda_function" "facebook_webhook"' in main_tf
    assert 'resource "aws_lambda_function" "rest_webhook"' in main_tf
    assert 'resource "aws_api_gateway_rest_api" "webhooks"' in main_tf
    assert '/webhooks/facebook' in main_tf
    assert '/webhooks/rest' in main_tf

    # Ensure handler paths and environment variables are present
    assert 'lambda.handlers.webhooks.facebook.handler' in main_tf
    assert 'lambda.handlers.webhooks.rest.handler' in main_tf
    assert 'FACEBOOK_APP_SECRET' in main_tf
    assert 'FACEBOOK_VERIFY_TOKEN' in main_tf
    assert 'FORWARDING_ENDPOINT' in main_tf

    # Validate variables file contains expected inputs
    with open("infra/terraform/webhook-lambdas/variables.tf", "r", encoding="utf-8") as f:
        vars_tf = f.read()
    for v in [
        "region",
        "lambda_timeout",
        "lambda_memory",
        "api_gateway_stage",
        "forwarding_endpoint",
        "forwarding_sqs_url",
        "facebook_app_secret",
        "facebook_verify_token",
        "facebook_package",
        "rest_package",
    ]:
        assert f'variable "{v}"' in vars_tf

    # Validate outputs present
    with open("infra/terraform/webhook-lambdas/outputs.tf", "r", encoding="utf-8") as f:
        outputs_tf = f.read()
    assert 'output "facebook_webhook_url"' in outputs_tf
    assert 'output "rest_webhook_url"' in outputs_tf
    assert 'output "lambda_arns"' in outputs_tf