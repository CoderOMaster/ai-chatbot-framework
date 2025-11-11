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
  description = "IAM role ARN for Lambda execution"
  type        = string
}

variable "lambda_zip_path" {
  description = "Path to packaged Lambda zip"
  type        = string
}

variable "layer_zip_path" {
  description = "Path to packaged Layer zip"
  type        = string
}

variable "llm_base_url" {
  description = "Base URL for LLM API"
  type        = string
}

variable "llm_api_key" {
  description = "API key for LLM API"
  type        = string
  sensitive   = true
}

variable "llm_model_name" {
  description = "Model name for LLM"
  type        = string
}

variable "llm_timeout_secs" {
  description = "Client timeout in seconds"
  type        = number
  default     = 25
}

variable "llm_max_retries" {
  description = "Max retries for client calls"
  type        = number
  default     = 2
}

variable "llm_retry_backoff_secs" {
  description = "Initial backoff for retries"
  type        = number
  default     = 1.5
}

variable "prompt_template_name" {
  description = "Prompt template filename"
  type        = string
  default     = "ZERO_SHOT_LEARNING_PROMPT.md"
}