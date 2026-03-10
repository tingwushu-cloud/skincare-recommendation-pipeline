###############################################################
# modules/redshift/variables.tf
###############################################################

variable "project" {
  description = "Project name used for naming and tagging all resources"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "redshift_admin_password" {
  description = "Admin password for Redshift Serverless"
  type        = string
  sensitive   = true
}

variable "redshift_role_arn" {
  description = "IAM role ARN for Redshift to access S3"
  type        = string
}
