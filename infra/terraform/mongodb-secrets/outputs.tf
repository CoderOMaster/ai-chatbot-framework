output "secrets_arn" {
  description = "ARN of the created Secrets Manager secret"
  value       = aws_secretsmanager_secret.mongodb_credentials.arn
}