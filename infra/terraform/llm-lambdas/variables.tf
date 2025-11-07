variable "region" {
  description = "AWS region"
  type        = string
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 30
}

variable "lambda_memory" {
  description = "Lambda memory in MB"
  type        = number
  default     = 256
}

variable "lambda_role_arn" {
  description = "IAM role ARN for the Lambda function"
  type        = string
}

variable "llm_base_url" {
  description = "Base URL for the OpenAI-compatible LLM endpoint"
  type        = string
}

variable "llm_api_key" {
  description = "API key for the LLM provider (can be empty for local models)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "llm_model_name" {
  description = "Model name to use for the LLM"
  type        = string
}