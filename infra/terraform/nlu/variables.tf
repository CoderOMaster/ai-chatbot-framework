variable "region" { type = string }
variable "cluster_arn" { type = string }
variable "execution_role_arn" { type = string }
variable "task_role_arn" { type = string }
variable "subnets" { type = list(string) }
variable "security_groups" { type = list(string) }
variable "image" { type = string }
variable "desired_count" { type = number default = 1 }
variable "runtime_cpu" { type = string default = "512" }
variable "runtime_memory" { type = string default = "1024" }
variable "model_dir" { type = string default = "/models" }
variable "spacy_model" { type = string default = "xx_core_web_sm" }