output "alb_dns_name" {
  description = "ALB DNS name."
  value       = aws_lb.alb.dns_name
}

output "api_domain" {
  description = "Public API domain attached to Route53."
  value       = aws_route53_record.api_alias.fqdn
}

output "api_base_url" {
  description = "Public HTTPS base URL."
  value       = "https://${aws_route53_record.api_alias.fqdn}"
}

output "ecr_repository_url" {
  description = "ECR repository URL for the API image."
  value       = aws_ecr_repository.api.repository_url
}

output "api_key_secret_arn" {
  description = "Secrets Manager secret ARN for API_KEY (set the value out-of-band)."
  value       = aws_secretsmanager_secret.api_key.arn
}
