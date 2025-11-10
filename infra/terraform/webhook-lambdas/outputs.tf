output "facebook_webhook_url" {
  value = "${aws_api_gateway_deployment.this.invoke_url}${var.api_gateway_stage}/webhooks/facebook"
}

output "rest_webhook_url" {
  value = "${aws_api_gateway_deployment.this.invoke_url}${var.api_gateway_stage}/webhooks/rest"
}

output "lambda_arns" {
  value = {
    facebook = aws_lambda_function.facebook_webhook.arn
    rest     = aws_lambda_function.rest_webhook.arn
  }
}