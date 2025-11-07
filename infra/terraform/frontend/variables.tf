variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "bucket_name" {
  description = "Name of the S3 bucket to host static frontend assets"
  type        = string
}

variable "force_destroy" {
  description = "Force destroy S3 bucket on terraform destroy"
  type        = bool
  default     = false
}