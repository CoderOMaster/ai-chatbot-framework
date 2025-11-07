output "secrets_arn" {
  value       = aws_secretsmanager_secret.mongodb_credentials.arn
  description = "ARN of the MongoDB credentials secret"
}