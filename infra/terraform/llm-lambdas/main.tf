terraform {
  required_version = ">= 1.5.0"
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

# Optional Lambda Layer to hold heavy LLM clients (langchain/openai)
resource "aws_lambda_layer_version" "llm_client_layer" {
  filename                 = "../../../../layers/llm_client_layer.zip"
  layer_name               = "llm-client-layer"
  compatible_runtimes      = ["python3.11"]
  description              = "Layer with langchain/openai and related heavy deps"
  retain                   = true
}

# IAM role for the function
resource "aws_iam_role" "zero_shot_llm_role" {
  name               = "zero-shot-llm-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = "sts:AssumeRole",
      Effect = "Allow",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "basic_exec" {
  role       = aws_iam_role.zero_shot_llm_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "zero_shot_llm" {
  function_name = "zero-shot-llm"
  role          = aws_iam_role.zero_shot_llm_role.arn
  runtime       = "python3.11"
  handler       = "lambda_handlers.llm.zero_shot.handler"

  filename         = "../../../../dist/zero-shot-llm.zip"
  source_code_hash = filebase64sha256("../../../../dist/zero-shot-llm.zip")

  timeout = var.lambda_timeout
  memory_size = var.lambda_memory

  layers = [
    aws_lambda_layer_version.llm_client_layer.arn
  ]

  environment {
    variables = {
      LLM_BASE_URL   = var.llm_base_url
      LLM_API_KEY    = var.llm_api_key
      LLM_MODEL_NAME = var.llm_model_name
      RETRY_ATTEMPTS = var.retry_attempts
      PROMPT_DIR     = var.prompt_dir
    }
  }
}

output "zero_shot_llm_function_name" {
  value = aws_lambda_function.zero_shot_llm.function_name
}