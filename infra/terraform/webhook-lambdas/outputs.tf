output "facebook_webhook_url" {
  value = "https://{api_id}.execute-api.${var.region}.amazonaws.com/${var.api_gateway_stage}/webhooks/facebook"
}

output "rest_webhook_url" {
  value = "https://{api_id}.execute-api.${var.region}.amazonaws.com/${var.api_gateway_stage}/webhooks/rest"
}

output "lambda_arns" {
  value = [
    aws_lambda_function.facebook_webhook.arn,
    aws_lambda_function.rest_webhook.arn
  ]
}