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
  default     = ""
}

variable "require_api_key" {
  type        = bool
  description = "Require X-API-Key auth for /answer."
  default     = true
}

variable "allow_insecure_cors_wildcard" {
  type        = bool
  description = "Allow '*' CORS wildcard (not recommended for production)."
  default     = false
}

variable "max_concurrent_requests" {
  type        = number
  description = "In-process concurrency cap for /answer requests."
  default     = 16
}

variable "rag_generation_retries" {
  type        = number
  description = "Retries for generation when Ollama call fails."
  default     = 2
}

variable "rag_generation_retry_backoff_seconds" {
  type        = number
  description = "Sleep between generation retries."
  default     = 1
}

variable "rag_min_faiss_chunk_overlap" {
  type        = number
  description = "Minimum chunk overlap ratio required to enable FAISS hybrid retrieval."
  default     = 0.9
}

variable "enable_autoscaling" {
  type        = bool
  description = "Enable ECS service target tracking autoscaling."
  default     = true
}

variable "min_task_count" {
  type        = number
  description = "Minimum ECS tasks for autoscaling target."
  default     = 0
}

variable "max_task_count" {
  type        = number
  description = "Maximum ECS tasks for autoscaling target."
  default     = 4
}

variable "target_cpu_utilization" {
  type        = number
  description = "Target ECS CPU utilization percentage for autoscaling."
  default     = 70
}

variable "target_memory_utilization" {
  type        = number
  description = "Target ECS memory utilization percentage for autoscaling."
  default     = 75
}

variable "scale_in_cooldown_seconds" {
  type        = number
  description = "Autoscaling scale-in cooldown."
  default     = 120
}

variable "scale_out_cooldown_seconds" {
  type        = number
  description = "Autoscaling scale-out cooldown."
  default     = 60
}

variable "target_5xx_alarm_threshold" {
  type        = number
  description = "Threshold for ALB target 5xx alarm in one minute."
  default     = 20
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
