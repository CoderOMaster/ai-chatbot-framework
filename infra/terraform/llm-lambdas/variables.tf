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
  description = "Lambda memory size"
  type        = number
  default     = 256
}

variable "llm_base_url" {
  description = "Base URL for the LLM API"
  type        = string
  default     = "https://api.openai.com/v1"
}

variable "llm_api_key" {
  description = "API key for the LLM provider"
  type        = string
  sensitive   = true
}

variable "llm_model_name" {
  description = "Model name to use"
  type        = string
  default     = "gpt-4o-mini"
}

variable "retry_attempts" {
  description = "Number of retry attempts for LLM invocation"
  type        = number
  default     = 2
}

variable "prompt_dir" {
  description = "Path inside the package where prompts are stored"
  type        = string
  default     = "app/bot/nlu/llm/prompts"
}