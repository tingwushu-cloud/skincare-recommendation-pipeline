###############################################################
# modules/iam/main.tf
# Creates IAM roles and policies for all pipeline services
###############################################################

locals {
  prefix = "${var.project}-${var.environment}"
}

###############################################################
# GLUE ROLE
###############################################################
resource "aws_iam_role" "glue" {
  name = "${local.prefix}-glue-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project, Environment = var.environment }
}

resource "aws_iam_role_policy" "glue_s3" {
  name = "${local.prefix}-glue-s3-policy"
  role = aws_iam_role.glue.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.bucket_name}",
          "arn:aws:s3:::${var.bucket_name}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:${var.account_id}:log-group:/aws-glue/*"
      }
    ]
  })
}

# Attach AWS managed Glue service policy
resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

###############################################################
# LAMBDA ROLE
###############################################################
resource "aws_iam_role" "lambda" {
  name = "${local.prefix}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project, Environment = var.environment }
}

resource "aws_iam_role_policy" "lambda_permissions" {
  name = "${local.prefix}-lambda-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.bucket_name}",
          "arn:aws:s3:::${var.bucket_name}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = "arn:aws:dynamodb:*:${var.account_id}:table/*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:${var.account_id}:log-group:/aws/lambda/*"
      }
    ]
  })
}

###############################################################
# STEP FUNCTIONS ROLE
###############################################################
resource "aws_iam_role" "step_functions" {
  name = "${local.prefix}-step-functions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project, Environment = var.environment }
}

resource "aws_iam_role_policy" "step_functions_permissions" {
  name = "${local.prefix}-step-functions-policy"
  role = aws_iam_role.step_functions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns"]
        Resource = "arn:aws:glue:*:${var.account_id}:job/*"
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:*:${var.account_id}:function:*"
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = "arn:aws:sns:*:${var.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogDelivery",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

###############################################################
# EVENTBRIDGE ROLE
###############################################################
resource "aws_iam_role" "eventbridge" {
  name = "${local.prefix}-eventbridge-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project, Environment = var.environment }
}

resource "aws_iam_role_policy" "eventbridge_permissions" {
  name = "${local.prefix}-eventbridge-policy"
  role = aws_iam_role.eventbridge.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = "arn:aws:states:*:${var.account_id}:stateMachine:*"
    }]
  })
}

###############################################################
# DEVELOPER USER POLICY (skincare-rec-user)
###############################################################
resource "aws_iam_user_policy" "developer" {
  name = "${local.prefix}-developer-policy"
  user = "skincare-rec-user"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Read Lambda configs and logs for debugging
        Effect = "Allow"
        Action = [
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:InvokeFunction",
          "lambda:ListFunctions",
        ]
        Resource = "arn:aws:lambda:eu-central-1:${var.account_id}:function:*"
      },
      {
        # Read CloudWatch logs
        Effect = "Allow"
        Action = [
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
          "logs:TailLogEvents",
          "logs:StartLiveTail",
        ]
        Resource = "arn:aws:logs:eu-central-1:${var.account_id}:log-group:*"
      },
      {
        # Read Step Functions executions
        Effect = "Allow"
        Action = [
          "states:ListExecutions",
          "states:DescribeExecution",
          "states:GetExecutionHistory",
        ]
        Resource = "*"
      }
    ]
  })
}

###############################################################
# REDSHIFT ROLE
###############################################################
resource "aws_iam_role" "redshift" {
  name = "${local.prefix}-redshift-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "redshift.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project, Environment = var.environment }
}

resource "aws_iam_role_policy" "redshift_s3" {
  name = "${local.prefix}-redshift-s3-policy"
  role = aws_iam_role.redshift.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.bucket_name}",
          "arn:aws:s3:::${var.bucket_name}/*"
        ]
      }
    ]
  })
}