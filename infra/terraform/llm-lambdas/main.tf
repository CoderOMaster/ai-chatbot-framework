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

variable "zero_shot_lambda_zip" {
  description = "Path to the ZIP package for the zero-shot LLM lambda (should include lambda_handlers/, ai_chatbot_common/ if needed, and function deps)"
  type        = string
}

variable "llm_client_layer_zip" {
  description = "Path to the ZIP package for the LLM client layer containing langchain/openai and dependencies"
  type        = string
}

resource "aws_lambda_layer_version" "llm_client_layer" {
  filename   = var.llm_client_layer_zip
  layer_name = "llm-client-layer"
  compatible_runtimes = ["python3.11", "python3.12"]
}

resource "aws_lambda_function" "zero_shot_llm" {
  function_name = "zero-shot-llm"
  filename      = var.zero_shot_lambda_zip
  source_code_hash = filebase64sha256(var.zero_shot_lambda_zip)

  handler = "lambda_handlers.llm.zero_shot.handler"
  runtime = "python3.11"

  timeout      = var.lambda_timeout
  memory_size  = var.lambda_memory

  role = var.lambda_role_arn

  layers = [aws_lambda_layer_version.llm_client_layer.arn]

  environment {
    variables = {
      LLM_BASE_URL   = var.llm_base_url
      LLM_API_KEY    = var.llm_api_key
      LLM_MODEL_NAME = var.llm_model_name
    }
  }
}