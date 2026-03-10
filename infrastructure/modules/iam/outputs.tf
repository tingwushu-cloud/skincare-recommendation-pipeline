output "glue_role_arn"            { value = aws_iam_role.glue.arn }
output "lambda_role_arn"          { value = aws_iam_role.lambda.arn }
output "step_functions_role_arn"  { value = aws_iam_role.step_functions.arn }
output "eventbridge_role_arn"     { value = aws_iam_role.eventbridge.arn }
output "redshift_role_arn"        { value = aws_iam_role.redshift.arn }
