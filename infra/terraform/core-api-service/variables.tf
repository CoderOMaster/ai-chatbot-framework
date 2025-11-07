variable "region" { type = string }
variable "name" { type = string, default = "core-api" }
variable "cluster_name" { type = string, default = "core-api-cluster" }
variable "image" { type = string }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "private_subnet_ids" { type = list(string) }
variable "alb_sg_id" { type = string }
variable "service_sg_id" { type = string }
variable "mongodb_host" { type = string }
variable "mongodb_database" { type = string }
variable "model_forwarding_endpoint" { type = string, default = "" }
variable "healthcheck_path" { type = string, default = "/ready" }
variable "task_cpu" { type = string, default = "512" }
variable "task_memory" { type = string, default = "1024" }
variable "desired_count" { type = number, default = 1 }