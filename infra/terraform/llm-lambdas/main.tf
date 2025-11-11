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

resource "aws_lambda_layer_version" "llm_client_layer" {
  filename   = var.layer_zip_path
  layer_name = "llm-client-layer"
  compatible_runtimes = ["python3.11"]
  description = "Layer containing langchain/openai clients"
}

resource "aws_lambda_function" "zero_shot_llm" {
  function_name = "zero-shot-llm"
  role          = var.lambda_role_arn
  handler       = "lambda.handlers.llm.zero_shot.handler"
  runtime       = "python3.11"
  filename      = var.lambda_zip_path
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  layers = [aws_lambda_layer_version.llm_client_layer.arn]

  environment {
    variables = {
      LLM_BASE_URL  = var.llm_base_url
      LLM_API_KEY   = var.llm_api_key
      LLM_MODEL_NAME = var.llm_model_name
      LLM_TIMEOUT_SECS = var.llm_timeout_secs
      LLM_MAX_RETRIES = var.llm_max_retries
      LLM_RETRY_BACKOFF_SECS = var.llm_retry_backoff_secs
      PROMPT_TEMPLATE_NAME = var.prompt_template_name
    }
  }
}