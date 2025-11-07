variable "region" {
  description = "AWS region"
  type        = string
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 10
}

variable "lambda_memory" {
  description = "Lambda memory size in MB"
  type        = number
  default     = 256
}

variable "api_gateway_stage" {
  description = "API Gateway stage name"
  type        = string
  default     = "prod"
}

variable "facebook_lambda_zip" {
  description = "Path to the zipped Facebook webhook Lambda package"
  type        = string
}

variable "rest_lambda_zip" {
  description = "Path to the zipped REST webhook Lambda package"
  type        = string
}

variable "facebook_app_secret" {
  description = "Facebook App Secret used to validate signatures"
  type        = string
  sensitive   = true
}

variable "facebook_verify_token" {
  description = "Facebook Verify Token for webhook verification (GET)"
  type        = string
  default     = ""
}

variable "forwarding_endpoint" {
  description = "Internal HTTP endpoint to forward messages to (if not using SQS)"
  type        = string
  default     = ""
}

variable "forwarding_sqs_url" {
  description = "SQS queue URL to forward messages to (optional)"
  type        = string
  default     = ""
}

variable "enable_sqs" {
  description = "If true, attach SQS permissions to Lambda role"
  type        = bool
  default     = false
}