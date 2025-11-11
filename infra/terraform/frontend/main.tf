terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# S3 bucket for static site (optional)
resource "aws_s3_bucket" "frontend_static_bucket" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_website_configuration" "frontend_website" {
  count  = var.enable_static_hosting ? 1 : 0
  bucket = aws_s3_bucket.frontend_static_bucket.id

  index_document {
    suffix = "index.html"
  }
  error_document {
    key = "404.html"
  }
}

# CloudFront distribution for S3 origin (optional)
resource "aws_cloudfront_distribution" "frontend_cdn" {
  count = var.enable_cdn ? 1 : 0

  origin {
    domain_name = aws_s3_bucket.frontend_static_bucket.bucket_regional_domain_name
    origin_id   = "s3-frontend-origin"
  }

  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "s3-frontend-origin"

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 3600
    max_ttl                = 86400
  }

  price_class = "PriceClass_100"

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}