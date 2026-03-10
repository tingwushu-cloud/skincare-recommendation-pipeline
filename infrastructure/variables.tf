###############################################################
# variables.tf — Input variable definitions
###############################################################

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "eu-central-1"
}

variable "project" {
  description = "Project name used for naming and tagging all resources"
  type        = string
  default     = "beauty-boba"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "pipeline_bucket_name" {
  description = "Name of the S3 bucket for the data pipeline (bronze/silver/gold layers)"
  type        = string
}

variable "account_id" {
  description = "Your 12-digit AWS account ID (from: aws sts get-caller-identity)"
  type        = string
  sensitive   = true
}

variable "alert_email" {
  description = "Email address to receive SNS pipeline failure alerts"
  type        = string
}

variable "redshift_admin_password" {
  description = "Admin password for Redshift Serverless"
  type        = string
  sensitive   = true
}