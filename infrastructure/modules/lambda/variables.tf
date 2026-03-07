variable "project"             { type = string }
variable "environment"         { type = string }
variable "bucket_name"         { type = string }
variable "lambda_role_arn"     { type = string }
variable "dynamodb_table_name" { type = string }

variable "ecr_account_id" {
  description = "AWS account ID where ECR repositories are hosted"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}