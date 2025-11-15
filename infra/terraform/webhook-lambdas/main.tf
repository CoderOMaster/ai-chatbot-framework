terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

resource "aws_iam_role" "webhook_lambda_exec_role" {
  name               = "webhook-lambda-exec-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = "sts:AssumeRole",
      Effect = "Allow",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cw" {
  role       = aws_iam_role.webhook_lambda_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Package and deploy two lambda functions (expects external packaging – e.g., archive_file)
resource "aws_lambda_function" "facebook_webhook" {
  function_name = "facebook-webhook"
  role          = aws_iam_role.webhook_lambda_exec_role.arn
  handler       = "lambda.handlers.webhooks.facebook.handler"
  runtime       = "python3.11"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  filename         = var.facebook_package
  source_code_hash = filebase64sha256(var.facebook_package)

  environment {
    variables = {
      FACEBOOK_APP_SECRET = var.facebook_app_secret
      FACEBOOK_VERIFY_TOKEN = var.facebook_verify_token
      FORWARDING_ENDPOINT = var.forwarding_endpoint
      FORWARDING_SQS_URL  = var.forwarding_sqs_url
    }
  }
}

resource "aws_lambda_function" "rest_webhook" {
  function_name = "rest-webhook"
  role          = aws_iam_role.webhook_lambda_exec_role.arn
  handler       = "lambda.handlers.webhooks.rest.handler"
  runtime       = "python3.11"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  filename         = var.rest_package
  source_code_hash = filebase64sha256(var.rest_package)

  environment {
    variables = {
      FORWARDING_ENDPOINT = var.forwarding_endpoint
    }
  }
}

# API Gateway - minimal example (proxy to lambdas)
resource "aws_api_gateway_rest_api" "webhooks" {
  name        = "webhooks-api"
  description = "API Gateway for webhook lambdas"
}

# Facebook POST /webhooks/facebook
resource "aws_api_gateway_resource" "facebook" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  parent_id   = aws_api_gateway_rest_api.webhooks.root_resource_id
  path_part   = "webhooks"
}

resource "aws_api_gateway_resource" "facebook_child" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  parent_id   = aws_api_gateway_resource.facebook.id
  path_part   = "facebook"
}

resource "aws_api_gateway_method" "facebook_post" {
  rest_api_id   = aws_api_gateway_rest_api.webhooks.id
  resource_id   = aws_api_gateway_resource.facebook_child.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "facebook_post" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  resource_id = aws_api_gateway_resource.facebook_child.id
  http_method = aws_api_gateway_method.facebook_post.http_method
  type        = "AWS_PROXY"
  integration_http_method = "POST"
  uri         = aws_lambda_function.facebook_webhook.invoke_arn
}

# REST POST /webhooks/rest
resource "aws_api_gateway_resource" "rest_child" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  parent_id   = aws_api_gateway_resource.facebook.id
  path_part   = "rest"
}

resource "aws_api_gateway_method" "rest_post" {
  rest_api_id   = aws_api_gateway_rest_api.webhooks.id
  resource_id   = aws_api_gateway_resource.rest_child.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "rest_post" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  resource_id = aws_api_gateway_resource.rest_child.id
  http_method = aws_api_gateway_method.rest_post.http_method
  type        = "AWS_PROXY"
  integration_http_method = "POST"
  uri         = aws_lambda_function.rest_webhook.invoke_arn
}

resource "aws_lambda_permission" "apigw_facebook" {
  statement_id  = "AllowAPIGatewayInvokeFacebook"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.facebook_webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.webhooks.execution_arn}/*/POST/webhooks/facebook"
}

resource "aws_lambda_permission" "apigw_rest" {
  statement_id  = "AllowAPIGatewayInvokeRest"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rest_webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.webhooks.execution_arn}/*/POST/webhooks/rest"
}

resource "aws_api_gateway_deployment" "webhooks" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  stage_name  = var.api_gateway_stage
  depends_on = [
    aws_api_gateway_integration.facebook_post,
    aws_api_gateway_integration.rest_post
  ]
}