variable "region" { type = string }
variable "image" { type = string }
variable "mongodb_host" { type = string }
variable "mongodb_database" { type = string }
variable "model_forwarding_endpoint" { type = string }
variable "task_cpu" { type = string default = "512" }
variable "task_memory" { type = string default = "1024" }
variable "desired_count" { type = number default = 1 }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "private_subnet_ids" { type = list(string) }