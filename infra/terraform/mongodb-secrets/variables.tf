variable "region" {
  type    = string
  default = "us-east-1"
}

variable "secret_name_prefix" {
  type    = string
  default = "chatbot/mongodb"
}

variable "mongodb_host" {
  type    = string
  default = "localhost"
}

variable "mongodb_port" {
  type    = number
  default = 27017
}

variable "mongodb_username" {
  type    = string
  default = ""
}

variable "mongodb_password" {
  type    = string
  default = ""
}

variable "mongodb_database" {
  type    = string
  default = "ai_chatbot"
}