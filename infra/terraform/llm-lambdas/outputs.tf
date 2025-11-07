output "zero_shot_llm_function_name" {
  value       = aws_lambda_function.zero_shot_llm.function_name
  description = "Name of the zero-shot LLM Lambda function"
}

output "llm_client_layer_arn" {
  value       = aws_lambda_layer_version.llm_client_layer.arn
  description = "ARN of the LLM client Lambda layer"
}