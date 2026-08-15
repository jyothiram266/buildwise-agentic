variable "aws_region" {
  description = "AWS Region to deploy resources in"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 Instance Type"
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Name of existing AWS Key Pair for SSH access (optional)"
  type        = string
  default     = ""
}

variable "security_user" {
  description = "Username for HTTP Basic Auth Security Gateway"
  type        = string
  default     = "admin"
}

variable "security_password" {
  description = "Password for HTTP Basic Auth Security Gateway"
  type        = string
  default     = "Capstone2026!"
}

variable "openai_api_key" {
  description = "OpenAI API Key for live LLM responses"
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_repo" {
  description = "Git repository URL to clone"
  type        = string
  default     = "https://github.com/YESVIN2807/buildwise-agentic.git"
}
