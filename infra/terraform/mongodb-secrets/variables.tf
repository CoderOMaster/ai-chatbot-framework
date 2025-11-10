variable "region" {
  description = "AWS region to deploy secrets"
  type        = string
}

variable "secret_name_prefix" {
  description = "Prefix for the MongoDB secret name"
  type        = string
  default     = "chatbot/mongodb"
}