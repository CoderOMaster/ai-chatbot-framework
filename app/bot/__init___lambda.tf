#############################
# Terraform sample (main.tf)
#############################

provider "aws" {
  region = var.region
}

resource "aws_iam_role" "lambda_exec" {
  name = "lambda_exec_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = { Service = "lambda.amazonaws.com" }
      }
    ]
  })
}

resource "aws_iam_policy" "lambda_policy" {
  name = "lambda_policy"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"], Resource = "arn:aws:logs:*:*:*" },
      { Effect = "Allow", Action = ["s3:GetObject","s3:PutObject"], Resource = "arn:aws:s3:::${var.s3_bucket}/*" },
      { Effect = "Allow", Action = ["dynamodb:GetItem","dynamodb:PutItem"], Resource = "${var.dynamodb_table_arn}" }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "attach" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}

resource "aws_lambda_function" "api_lambda" {
  filename         = var.lambda_zip_path
  function_name    = var.lambda_name
  role             = aws_iam_role.lambda_exec.arn
  handler          = "__init__.lambda_handler"
  runtime          = "python3.11"
  memory_size      = 1024
  timeout          = 300

  environment {
    variables = {
      REGION         = var.region
      BUCKET_NAME    = var.s3_bucket
      TABLE_NAME     = var.dynamodb_table_name
      DEFAULT_KEY    = "default-key"
      LOG_LEVEL      = "INFO"
    }
  }
}

# API Gateway (REST API) example
resource "aws_api_gateway_rest_api" "api" {
  name = "lambda-api"
}

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "any_method" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "ANY"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.any_method.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.api_lambda.invoke_arn
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "deployment" {
  depends_on = [aws_api_gateway_integration.lambda_integration]
  rest_api_id = aws_api_gateway_rest_api.api.id
  stage_name = "prod"
}

#############################
# variables.tf (partial)
#############################

# variable "region" { default = "us-east-1" }
# variable "s3_bucket" {}
# variable "dynamodb_table_name" {}
# variable "dynamodb_table_arn" {}
# variable "lambda_zip_path" {}
# variable "lambda_name" { default = "my-lambda" }
