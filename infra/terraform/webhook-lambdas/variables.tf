variable "region" {
  description = "AWS region"
  type        = string
}

variable "lambda_timeout" {
  description = "Lambda timeout seconds"
  type        = number
  default     = 10
}

variable "lambda_memory" {
  description = "Lambda memory size"
  type        = number
  default     = 256
}

variable "api_gateway_stage" {
  description = "API Gateway stage name"
  type        = string
  default     = "dev"
}

variable "forwarding_endpoint" {
  description = "Internal HTTP endpoint to forward webhooks"
  type        = string
}

variable "forwarding_sqs_url" {
  description = "Optional SQS queue URL for async processing"
  type        = string
  default     = ""
}

variable "facebook_app_secret" {
  description = "Facebook App Secret"
  type        = string
  sensitive   = true
}

variable "facebook_verify_token" {
  description = "Facebook Verify Token"
  type        = string
  sensitive   = true
}

variable "facebook_package" {
  description = "Path to packaged zip for facebook lambda"
  type        = string
}

variable "rest_package" {
  description = "Path to packaged zip for rest lambda"
  type        = string
}