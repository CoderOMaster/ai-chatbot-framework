provider "aws" {
  region = var.aws_region
}

variable "aws_region" { default = "us-east-1" }
variable "lambda_s3_key" { default = "lambda_deploy_package.zip" }

resource "aws_iam_role" "lambda_exec" {
  name = "chat-schemas-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = "sts:AssumeRole",
      Effect = "Allow",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "chat-schemas-lambda-policy"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:GetItem"
        ],
        Resource = "arn:aws:dynamodb:${var.aws_region}:*:table/${var.chat_table_name}"
      },
      {
        Effect = "Allow",
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        Resource = "*"
      }
    ]
  })
}

variable "chat_table_name" { default = "chat-logs-table" }

resource "aws_lambda_function" "chat_schemas" {
  filename         = "${path.module}/build/${var.lambda_s3_key}" # ZIP containing schemas.py and dependencies
  function_name    = "chat-schemas-lambda"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "schemas.lambda_handler"
  runtime          = "python3.10"
  memory_size      = 1024
  timeout          = 300

  environment {
    variables = {
      CHAT_TABLE_NAME = var.chat_table_name
      AWS_REGION      = var.aws_region
      LOG_LEVEL       = "INFO"
    }
  }

  # layers = ["arn:aws:lambda:...:layer:pydantic:1"] # optional
}

# API Gateway (REST API) - simple proxy integration
resource "aws_api_gateway_rest_api" "api" {
  name = "chat-schemas-api"
}

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "proxy_method" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "ANY"
  authorization = "NONE"
  request_parameters = {
    "method.request.path.proxy" = true
  }
}

resource "aws_api_gateway_integration" "lambda_integration" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_method.http_method
  integration_http_method = "POST"
  type = "AWS_PROXY"
  uri  = aws_lambda_function.chat_schemas.invoke_arn
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.chat_schemas.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "arn:aws:execute-api:${var.aws_region}:*: ${aws_api_gateway_rest_api.api.id}/*/*/{proxy+}"
}

output "invoke_url" {
  value = "https://${aws_api_gateway_rest_api.api.id}.execute-api.${var.aws_region}.amazonaws.com/prod/"
}
