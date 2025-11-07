terraform {
  required_version = ">= 1.3.0"
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

# IAM role for Lambda execution
resource "aws_iam_role" "webhook_lambda_exec_role" {
  name               = "webhook-lambda-exec-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action    = "sts:AssumeRole",
        Effect    = "Allow",
        Principal = { Service = "lambda.amazonaws.com" }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.webhook_lambda_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Optional: SQS send permissions
resource "aws_iam_role_policy_attachment" "lambda_sqs_send" {
  count      = var.enable_sqs ? 1 : 0
  role       = aws_iam_role.webhook_lambda_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSQSFullAccess"
}

# Package artifacts are provided as variables (zip paths)

resource "aws_lambda_function" "facebook_webhook" {
  function_name = "facebook-webhook"
  handler       = "lambda_handlers.webhooks.facebook.handler"
  role          = aws_iam_role.webhook_lambda_exec_role.arn
  runtime       = "python3.11"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  filename         = var.facebook_lambda_zip
  source_code_hash = filebase64sha256(var.facebook_lambda_zip)

  environment {
    variables = {
      FACEBOOK_APP_SECRET   = var.facebook_app_secret
      FACEBOOK_VERIFY_TOKEN = var.facebook_verify_token
      FORWARDING_ENDPOINT   = var.forwarding_endpoint
      FORWARDING_SQS_URL    = var.forwarding_sqs_url
    }
  }
}

resource "aws_lambda_function" "rest_webhook" {
  function_name = "rest-webhook"
  handler       = "lambda_handlers.webhooks.rest.handler"
  role          = aws_iam_role.webhook_lambda_exec_role.arn
  runtime       = "python3.11"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  filename         = var.rest_lambda_zip
  source_code_hash = filebase64sha256(var.rest_lambda_zip)

  environment {
    variables = {
      FORWARDING_ENDPOINT = var.forwarding_endpoint
      FORWARDING_SQS_URL  = var.forwarding_sqs_url
    }
  }
}

# API Gateway for webhooks
resource "aws_api_gateway_rest_api" "webhooks" {
  name = "webhooks-api"
}

resource "aws_api_gateway_resource" "webhooks_root" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  parent_id   = aws_api_gateway_rest_api.webhooks.root_resource_id
  path_part   = "webhooks"
}

resource "aws_api_gateway_resource" "facebook" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  parent_id   = aws_api_gateway_resource.webhooks_root.id
  path_part   = "facebook"
}

resource "aws_api_gateway_resource" "rest" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  parent_id   = aws_api_gateway_resource.webhooks_root.id
  path_part   = "rest"
}

# Facebook GET verify
resource "aws_api_gateway_method" "facebook_get" {
  rest_api_id   = aws_api_gateway_rest_api.webhooks.id
  resource_id   = aws_api_gateway_resource.facebook.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "facebook_get" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  resource_id = aws_api_gateway_resource.facebook.id
  http_method = aws_api_gateway_method.facebook_get.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.facebook_webhook.invoke_arn
}

# Facebook POST webhook
resource "aws_api_gateway_method" "facebook_post" {
  rest_api_id   = aws_api_gateway_rest_api.webhooks.id
  resource_id   = aws_api_gateway_resource.facebook.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "facebook_post" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  resource_id = aws_api_gateway_resource.facebook.id
  http_method = aws_api_gateway_method.facebook_post.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.facebook_webhook.invoke_arn
}

# REST webhook POST
resource "aws_api_gateway_method" "rest_post" {
  rest_api_id   = aws_api_gateway_rest_api.webhooks.id
  resource_id   = aws_api_gateway_resource.rest.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "rest_post" {
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  resource_id = aws_api_gateway_resource.rest.id
  http_method = aws_api_gateway_method.rest_post.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.rest_webhook.invoke_arn
}

resource "aws_api_gateway_deployment" "webhooks" {
  depends_on = [
    aws_api_gateway_integration.facebook_get,
    aws_api_gateway_integration.facebook_post,
    aws_api_gateway_integration.rest_post,
  ]
  rest_api_id = aws_api_gateway_rest_api.webhooks.id
  stage_name  = var.api_gateway_stage
}

# Permissions for API Gateway to invoke Lambdas
resource "aws_lambda_permission" "apigw_fb" {
  statement_id  = "AllowAPIGatewayInvokeFB"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.facebook_webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.webhooks.execution_arn}/*/*/webhooks/facebook"
}

resource "aws_lambda_permission" "apigw_rest" {
  statement_id  = "AllowAPIGatewayInvokeREST"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rest_webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.webhooks.execution_arn}/*/*/webhooks/rest"
}