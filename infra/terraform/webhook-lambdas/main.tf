terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

resource "aws_iam_role" "webhook_lambda_exec_role" {
  name = "webhook_lambda_exec_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  managed_policy_arns = [
    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
  ]
}

# Note: The lambda function resources below expect pre-built zip packages uploaded to S3
# or using a deployment mechanism. Here we outline the lambda resources and environment configuration.

resource "aws_lambda_function" "facebook_webhook" {
  filename         = var.facebook_lambda_package
  function_name    = "facebook_webhook"
  role             = aws_iam_role.webhook_lambda_exec_role.arn
  handler          = "lambda_handlers.webhooks.facebook.handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256(var.facebook_lambda_package)
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory

  environment {
    variables = {
      FACEBOOK_APP_SECRET  = var.facebook_app_secret
      FORWARDING_ENDPOINT  = var.forwarding_endpoint
      FORWARDING_SQS_URL   = var.forwarding_sqs_url
    }
  }

  depends_on = [aws_iam_role.webhook_lambda_exec_role]
}

resource "aws_lambda_function" "rest_webhook" {
  filename         = var.rest_lambda_package
  function_name    = "rest_webhook"
  role             = aws_iam_role.webhook_lambda_exec_role.arn
  handler          = "lambda_handlers.webhooks.rest.handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256(var.rest_lambda_package)
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory

  environment {
    variables = {
      FORWARDING_ENDPOINT = var.forwarding_endpoint
    }
  }

  depends_on = [aws_iam_role.webhook_lambda_exec_role]
}

# Output ARNs and example API Gateway triggers would be created in separate module
output "facebook_webhook_arn" {
  value = aws_lambda_function.facebook_webhook.arn
}

output "rest_webhook_arn" {
  value = aws_lambda_function.rest_webhook.arn
}