variable "region" {
  type    = string
  default = "us-east-1"
}

variable "lambda_timeout" {
  type    = number
  default = 30
}

variable "lambda_memory" {
  type    = number
  default = 256
}

variable "lambda_iam_role_arn" {
  type = string
}

variable "llm_base_url" {
  type = string
}

variable "llm_api_key" {
  type = string
  sensitive = true
}

variable "llm_model_name" {
  type = string
}