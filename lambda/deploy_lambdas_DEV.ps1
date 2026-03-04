# deploy_lambdas.ps1
# Packages and deploys both Lambda functions to AWS.
# Usage: .\deploy_lambdas.ps1
# Fixed for Windows/PowerShell: clean paths, LF compatible

$BUCKET        = "beauty-boba-sip-and-tint"
$REGION        = "eu-central-1"
$SIM_FUNCTION  = "beauty-boba-dev-similarity"
$LOAD_FUNCTION = "beauty-boba-dev-loader"
$S3_PREFIX     = "lambda-deployments"
$BASE          = $PSScriptRoot

Write-Host ""
Write-Host "=== Beauty Boba Lambda Deployment ===" -ForegroundColor Cyan
Write-Host "Base directory: $BASE"
Write-Host ""

# Validate folder structure (SIMPLE VERSION - FIXED PATHS)
$missing = $false
if (-Not (Test-Path "$BASE\similarity\handler.py"))      { Write-Host "MISSING: $BASE\similarity\handler.py" -ForegroundColor Red; $missing = $true } else { Write-Host "  OK: $BASE\similarity\handler.py" -ForegroundColor Green }
if (-Not (Test-Path "$BASE\similarity\requirements.txt")) { Write-Host "MISSING: $BASE\similarity\requirements.txt" -ForegroundColor Red; $missing = $true } else { Write-Host "  OK: $BASE\similarity\requirements.txt" -ForegroundColor Green }
if (-Not (Test-Path "$BASE\loader\handler.py"))           { Write-Host "MISSING: $BASE\loader\handler.py" -ForegroundColor Red; $missing = $true } else { Write-Host "  OK: $BASE\loader\handler.py" -ForegroundColor Green }
if (-Not (Test-Path "$BASE\loader\requirements.txt"))     { Write-Host "MISSING: $BASE\loader\requirements.txt" -ForegroundColor Red; $missing = $true } else { Write-Host "  OK: $BASE\loader\requirements.txt" -ForegroundColor Green }
if ($missing) {
    Write-Host "Fix missing files before running this script." -ForegroundColor Red
    exit 1
}

function Package-Lambda {
    param (
        [string]$Name,
        [string]$SourceDir,
        [string]$OutputZip
    )
    Write-Host ""
    Write-Host "Packaging $Name Lambda..." -ForegroundColor Yellow
    $PackageDir = "$SourceDir\package"
    if (Test-Path $PackageDir) { Remove-Item -Recurse -Force $PackageDir }
    New-Item -ItemType Directory -Path $PackageDir | Out-Null
    Write-Host "  Installing dependencies..."
    $pipArgs = @(
        "install",
        "-r", "$SourceDir\requirements.txt",
        "--target", $PackageDir,
        "--quiet",
        "--python-version", "3.11",
        "--platform", "manylinux2014_x86_64",
        "--only-binary=:all:"
    )
    & pip @pipArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: pip install failed for $Name" -ForegroundColor Red
        exit 1
    }
    Copy-Item "$SourceDir\handler.py" "$PackageDir\handler.py"
    if (Test-Path $OutputZip) { Remove-Item $OutputZip }
    Push-Location $PackageDir
    Compress-Archive -Path * -DestinationPath $OutputZip -Force
    Pop-Location
    Remove-Item -Recurse -Force $PackageDir
    $ZipSizeMB = [math]::Round((Get-Item $OutputZip).Length / 1MB, 1)
    Write-Host "  $Name.zip created ($ZipSizeMB MB)" -ForegroundColor Green
}

function Deploy-Lambda {
    param (
        [string]$FunctionName,
        [string]$ZipPath
    )
    $ZipSizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
    $DirectLimitMB = 65
    "`n[S3_UPLOAD]`n" | Out-File -FilePath "debug.txt" -Append  # Debug helper
    if ($ZipSizeMB -le $DirectLimitMB) {
        Write-Host "  Uploading directly ($ZipSizeMB MB)..." -ForegroundColor Yellow
        aws lambda update-function-code --function-name $FunctionName --zip-file "fileb://$ZipPath" --region $REGION | Out-Null
    } else {
        $ZipFilename = Split-Path $ZipPath -Leaf
        $S3Key = "$S3_PREFIX/$ZipFilename"
        Write-Host "  Zip is $ZipSizeMB MB - uploading via S3..." -ForegroundColor Yellow
        Write-Host "  Uploading to s3://$BUCKET/$S3Key..."
        aws s3 cp $ZipPath "s3://$BUCKET/$S3Key" --region $REGION
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: S3 upload failed for $FunctionName" -ForegroundColor Red
            exit 1
        }
        Write-Host "  Pointing Lambda at S3 object..."
        aws lambda update-function-code --function-name $FunctionName --s3-bucket $BUCKET --s3-key $S3Key --region $REGION | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: Failed to deploy $FunctionName" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  $FunctionName deployed successfully" -ForegroundColor Green
}

# Run packaging and deployment
Package-Lambda -Name "similarity" -SourceDir "$BASE\similarity" -OutputZip "$BASE\similarity.zip"
Package-Lambda -Name "loader" -SourceDir "$BASE\loader" -OutputZip "$BASE\loader.zip"

Write-Host ""
Write-Host "[3/4] Deploying similarity Lambda..." -ForegroundColor Yellow
Deploy-Lambda -FunctionName $SIM_FUNCTION -ZipPath "$BASE\similarity.zip"

Write-Host ""
Write-Host "[4/4] Deploying loader Lambda..." -ForegroundColor Yellow
Deploy-Lambda -FunctionName $LOAD_FUNCTION -ZipPath "$BASE\loader.zip"

Write-Host ""
Write-Host "=== Verifying deployments ===" -ForegroundColor Cyan
aws lambda get-function --function-name $SIM_FUNCTION --region $REGION --query "Configuration.[FunctionName,Runtime,CodeSize,LastModified]" --output table
aws lambda get-function --function-name $LOAD_FUNCTION --region $REGION --query "Configuration.[FunctionName,Runtime,CodeSize,LastModified]" --output table

Write-Host ""
Write-Host "Done! Both Lambdas deployed successfully." -ForegroundColor Green
Write-Host "Next step: trigger Step Functions from the AWS console."
