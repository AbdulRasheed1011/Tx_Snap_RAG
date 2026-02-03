variable "aws_region" {
  type        = string
  description = "AWS region to deploy into."
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Name prefix for resources."
  default     = "tx-snap-rag"
}

variable "image_tag" {
  type        = string
  description = "Docker image tag pushed to ECR."
  default     = "latest"
}

variable "desired_count" {
  type        = number
  description = "ECS desired tasks."
  default     = 1
}

variable "task_cpu" {
  type        = number
  description = "Task CPU units (1024 = 1 vCPU)."
  default     = 4096
}

variable "task_memory" {
  type        = number
  description = "Task memory (MiB)."
  default     = 8192
}

variable "task_ephemeral_storage_gb" {
  type        = number
  description = "Ephemeral storage for the task (GB). Used for Ollama model downloads."
  default     = 50
}

variable "ollama_model" {
  type        = string
  description = "Ollama model name."
  default     = "llama3.1"
}

variable "cors_allow_origins" {
  type        = string
  description = "Comma-separated origins for CORS (use * for all)."
  default     = "*"
}

variable "hosted_zone_name" {
  type        = string
  description = "Route53 hosted zone DNS name (e.g. example.com)."
}

variable "api_subdomain" {
  type        = string
  description = "Subdomain for the public API."
  default     = "api"
}

variable "hosted_zone_id" {
  type        = string
  description = "Optional Route53 hosted zone ID. Set this to avoid needing route53:ListHostedZones."
  default     = ""
}

variable "vpc_id" {
  type        = string
  description = "Optional VPC ID. Set this to avoid needing ec2:DescribeVpcs."
  default     = ""
}

variable "subnet_ids" {
  type        = list(string)
  description = "Optional subnet IDs. Set this to avoid needing ec2:DescribeSubnets."
  default     = []
}
