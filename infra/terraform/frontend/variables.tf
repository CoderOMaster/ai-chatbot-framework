variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "bucket_name" {
  description = "S3 bucket name for static frontend hosting"
  type        = string
}

variable "enable_static_hosting" {
  description = "Enable S3 static website hosting"
  type        = bool
  default     = true
}

variable "enable_cdn" {
  description = "Create CloudFront distribution"
  type        = bool
  default     = true
}