###############################################################
# main.tf — Root configuration
# Calls all modules and wires them together
###############################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # S3 backend — stores Terraform state remotely
  backend "s3" {
    bucket         = "js-bb-sat-tf-state"
    key            = "skincare-pipeline/terraform.tfstate"
    region         = "eu-central-1"
    #dynamodb_table = "terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

###############################################################
# Modules
###############################################################

module "iam" {
  source      = "./modules/iam"
  project     = var.project
  environment = var.environment
  bucket_name = var.pipeline_bucket_name
  account_id  = var.account_id
}

module "s3" {
  source      = "./modules/s3"
  project     = var.project
  environment = var.environment
  bucket_name = var.pipeline_bucket_name
  aws_region  = var.aws_region
  account_id  = var.account_id
}

module "dynamodb" {
  source      = "./modules/dynamodb"
  project     = var.project
  environment = var.environment
}

module "glue" {
  source            = "./modules/glue"
  project           = var.project
  environment       = var.environment
  bucket_name       = var.pipeline_bucket_name
  glue_role_arn     = module.iam.glue_role_arn
}

module "lambda" {
  source              = "./modules/lambda"
  project             = var.project
  environment         = var.environment
  bucket_name         = var.pipeline_bucket_name
  lambda_role_arn     = module.iam.lambda_role_arn
  dynamodb_table_name = module.dynamodb.table_name
  ecr_account_id      = "444398957152"
  aws_region          = "eu-central-1"
}

module "sns" {
  source            = "./modules/sns"
  project           = var.project
  environment       = var.environment
  alert_email       = var.alert_email
}

module "step_functions" {
  source                = "./modules/step_functions"
  project               = var.project
  environment           = var.environment
  glue_job_name         = module.glue.job_name
  lambda_similarity_arn = module.lambda.similarity_function_arn
  lambda_loader_arn     = module.lambda.loader_function_arn
  sns_topic_arn         = module.sns.topic_arn
  step_functions_role_arn = module.iam.step_functions_role_arn
}

module "eventbridge" {
  source               = "./modules/eventbridge"
  project              = var.project
  environment          = var.environment
  bucket_name          = var.pipeline_bucket_name
  state_machine_arn    = module.step_functions.state_machine_arn
  eventbridge_role_arn = module.iam.eventbridge_role_arn
}
