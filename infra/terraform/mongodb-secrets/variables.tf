variable "region" {
  description = "AWS region"
  type        = string
}

variable "secret_name_prefix" {
  description = "Prefix for MongoDB secret name"
  type        = string
  default     = "chatbot/mongodb"
}