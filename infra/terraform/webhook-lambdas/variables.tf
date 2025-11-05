variable "region" {
  type    = string
  default = "us-east-1"
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

variable "facebook_lambda_package" {
  type = string
}

variable "rest_lambda_package" {
  type = string
}

variable "facebook_app_secret" {
  type = string
  default = ""
}

variable "forwarding_endpoint" {
  type = string
  default = ""
}

variable "forwarding_sqs_url" {
  type = string
  default = ""
}