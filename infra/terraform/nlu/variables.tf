variable "region" { type = string }
variable "cluster_arn" { type = string }
variable "execution_role_arn" { type = string }
variable "task_role_arn" { type = string }
variable "image" { type = string }
variable "cpu" { type = string default = "512" }
variable "memory" { type = string default = "1024" }
variable "desired_count" { type = number default = 1 }
variable "subnets" { type = list(string) }
variable "security_groups" { type = list(string) }
variable "assign_public_ip" { type = bool default = false }
variable "spacy_lang_model" { type = string default = "xx_core_web_sm" }