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

resource "aws_lambda_layer_version" "llm_client_layer" {
  filename   = "layer.zip" # replace with built layer artifact
  layer_name = "llm_client_layer"
  compatible_runtimes = ["python3.11"]
  description = "Layer containing langchain and OpenAI SDKs"
}

resource "aws_lambda_function" "zero_shot_llm" {
  filename         = "zero_shot.zip" # replace with built function artifact
  function_name    = "zero_shot_llm"
  handler          = "lambda_handlers.llm.zero_shot.handler"
  runtime          = "python3.11"
  role             = var.lambda_iam_role_arn
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory
  layers           = [aws_lambda_layer_version.llm_client_layer.arn]

  environment {
    variables = {
      LLM_BASE_URL = var.llm_base_url
      LLM_API_KEY  = var.llm_api_key
      LLM_MODEL_NAME = var.llm_model_name
    }
  }
}

output "zero_shot_lambda_arn" {
  value = aws_lambda_function.zero_shot_llm.arn
}