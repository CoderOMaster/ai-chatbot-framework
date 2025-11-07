output "bucket_id" {
  description = "ID of the S3 bucket used for static hosting"
  value       = aws_s3_bucket.frontend_static_bucket.id
}

output "cloudfront_domain" {
  description = "CloudFront distribution domain name"
  value       = aws_cloudfront_distribution.frontend_cdn.domain_name
}