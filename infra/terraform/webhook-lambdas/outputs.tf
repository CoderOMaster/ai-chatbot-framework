output "facebook_webhook_url" {
  description = "Invoke URL for Facebook webhook"
  value       = "${aws_api_gateway_deployment.webhooks.invoke_url}${var.api_gateway_stage}/webhooks/facebook"
}

output "rest_webhook_url" {
  description = "Invoke URL for REST webhook"
  value       = "${aws_api_gateway_deployment.webhooks.invoke_url}${var.api_gateway_stage}/webhooks/rest"
}

output "lambda_arns" {
  description = "ARNs of deployed lambdas"
  value = {
    facebook = aws_lambda_function.facebook_webhook.arn
    rest     = aws_lambda_function.rest_webhook.arn
  }
}