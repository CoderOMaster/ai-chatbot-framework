// Terraform module for frontend static hosting (S3 + CloudFront)

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "aws_s3_bucket" "frontend_static_bucket" {
  bucket = var.bucket_name
  acl    = "public-read"
  tags = {
    Name = "frontend-static-bucket"
  }
}

# CloudFront distribution would reference the S3 bucket as origin. Additional resources like ACM cert and route53 can be added.
resource "aws_cloudfront_distribution" "frontend_cdn" {
  enabled = true
  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD", "OPTIONS"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "s3-origin"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
  }

  origins {
    domain_name = aws_s3_bucket.frontend_static_bucket.bucket_regional_domain_name
    origin_id   = "s3-origin"
  }

  default_root_object = "index.html"
  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}