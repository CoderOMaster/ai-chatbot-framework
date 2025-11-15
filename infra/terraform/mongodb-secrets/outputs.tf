output "secrets_arn" {
  description = "ARN of the MongoDB credentials secret"
  value       = aws_secretsmanager_secret.mongodb_credentials.arn
}