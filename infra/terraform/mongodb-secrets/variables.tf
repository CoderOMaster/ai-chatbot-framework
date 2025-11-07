variable "region" {
  type        = string
  description = "AWS region"
}

variable "secret_name_prefix" {
  type        = string
  description = "Prefix for secret name path"
  default     = "chatbot/mongodb"
}