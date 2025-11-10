variable "region" {
  type = string
}

variable "lambda_timeout" {
  type    = number
  default = 10
}

variable "lambda_memory" {
  type    = number
  default = 256
}

variable "api_gateway_stage" {
  type    = string
  default = "prod"
}

variable "forwarding_endpoint" {
  type = string
}

variable "forwarding_sqs_url" {
  type    = string
  default = null
}

variable "facebook_app_secret" {
  type = string
}