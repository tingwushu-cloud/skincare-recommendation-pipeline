###############################################################
# modules/redshift/main.tf
# Creates Redshift Serverless namespace and workgroup
###############################################################

resource "aws_redshiftserverless_namespace" "main" {
  namespace_name      = "${var.project}-${var.environment}"
  db_name             = "skincare"
  admin_username      = "admin"
  admin_user_password = var.redshift_admin_password
  iam_roles           = [var.redshift_role_arn]

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}

resource "aws_redshiftserverless_workgroup" "main" {
  namespace_name = aws_redshiftserverless_namespace.main.namespace_name
  workgroup_name = "${var.project}-${var.environment}"
  base_capacity  = 8  # minimum RPUs — smallest and cheapest option

  publicly_accessible = true

  tags = {
    Project     = var.project
    Environment = var.environment
  }
}
