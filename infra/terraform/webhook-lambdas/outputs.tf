output "facebook_webhook_url" {
  description = "Facebook webhook URL"
  value       = "https://${aws_api_gateway_rest_api.webhooks.id}.execute-api.${var.region}.amazonaws.com/${var.api_gateway_stage}/webhooks/facebook"
}

output "rest_webhook_url" {
  description = "Generic REST webhook URL"
  value       = "https://${aws_api_gateway_rest_api.webhooks.id}.execute-api.${var.region}.amazonaws.com/${var.api_gateway_stage}/webhooks/rest"
}

output "lambda_arns" {
  description = "ARNs of deployed webhook Lambdas"
  value = {
    facebook = aws_lambda_function.facebook_webhook.arn
    rest     = aws_lambda_function.rest_webhook.arn
  }
}