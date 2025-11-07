variable "region" { type = string }
variable "cluster_arn" { type = string }
variable "execution_role_arn" { type = string }
variable "task_role_arn" { type = string }
variable "runtime_image" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_ids" { type = list(string) }
variable "desired_count" { type = number default = 1 }
variable "runtime_cpu" { type = string default = "1024" }
variable "runtime_memory" { type = string default = "2048" }
variable "spacy_model" { type = string default = "xx_core_web_sm" }
variable "enable_efs" { type = bool default = true }