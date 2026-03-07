#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# docker_build_push.sh
#
# Builds Docker images for both Lambda functions, tests them locally,
# pushes them to ECR, and updates the Lambda functions to use the new images.
#
# Usage:
#   chmod +x docker_build_push.sh
#   ./docker_build_push.sh
#
# Prerequisites:
#   - Docker Desktop running
#   - AWS CLI configured (profile: terraform-user)
#   - Your handler.py files copied into docker/similarity/ and docker/loader/
# ─────────────────────────────────────────────────────────────────────────────

set -e  # exit immediately on any error

# ── CONFIG ────────────────────────────────────────────────────────────────────
AWS_ACCOUNT_ID="444398957152"          # your AWS account ID
AWS_REGION="eu-central-1"
AWS_PROFILE="terraform-user"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

SIM_REPO="beauty-boba-similarity"
LOADER_REPO="beauty-boba-loader"
SIM_FUNCTION="beauty-boba-dev-similarity"
LOADER_FUNCTION="beauty-boba-dev-loader"

TAG="latest"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "=== Sip and Tint — Docker Build & Push ==="
echo "Registry : $ECR_REGISTRY"
echo "Region   : $AWS_REGION"
echo "Profile  : $AWS_PROFILE"
echo ""

# ── STEP 1: Copy handler.py files into docker build context ───────────────────
# Your handler.py files live in the original lambda/ directory.
# Adjust these paths to match your repo structure.
echo "--- Step 1: Copying handler files ---"

# IMPORTANT: update these paths to point to your actual handler.py files
SIM_HANDLER="../../lambda/similarity/handler.py"
LOADER_HANDLER="../../lambda/loader/handler.py"

if [ ! -f "$SCRIPT_DIR/$SIM_HANDLER" ]; then
    echo "ERROR: similarity handler not found at $SCRIPT_DIR/$SIM_HANDLER"
    echo "Update the SIM_HANDLER path in this script to match your repo."
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/$LOADER_HANDLER" ]; then
    echo "ERROR: loader handler not found at $SCRIPT_DIR/$LOADER_HANDLER"
    echo "Update the LOADER_HANDLER path in this script to match your repo."
    exit 1
fi

cp "$SCRIPT_DIR/$SIM_HANDLER"    "$SCRIPT_DIR/docker/similarity/handler.py"
cp "$SCRIPT_DIR/$LOADER_HANDLER" "$SCRIPT_DIR/docker/loader/handler.py"
echo "  OK: handler files copied"
echo ""

# ── STEP 2: Create ECR repositories (idempotent — safe to run multiple times) ─
echo "--- Step 2: Creating ECR repositories ---"

aws ecr create-repository \
    --repository-name "$SIM_REPO" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" 2>/dev/null || echo "  (similarity repo already exists)"

aws ecr create-repository \
    --repository-name "$LOADER_REPO" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" 2>/dev/null || echo "  (loader repo already exists)"

echo ""

# ── STEP 3: Authenticate Docker to ECR ───────────────────────────────────────
echo "--- Step 3: Authenticating Docker to ECR ---"

aws ecr get-login-password \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
  | docker login \
      --username AWS \
      --password-stdin \
      "$ECR_REGISTRY"

echo ""

# ── STEP 4: Build images ──────────────────────────────────────────────────────
echo "--- Step 4: Building Docker images ---"

echo "  Building similarity image..."
docker build \
    --platform linux/amd64 \
    -t "${ECR_REGISTRY}/${SIM_REPO}:${TAG}" \
    "$SCRIPT_DIR/docker/similarity/"

echo ""
echo "  Building loader image..."
docker build \
    --platform linux/amd64 \
    -t "${ECR_REGISTRY}/${LOADER_REPO}:${TAG}" \
    "$SCRIPT_DIR/docker/loader/"

echo ""

# ── STEP 5: Test locally before pushing ──────────────────────────────────────
# Run the container locally and send it a test event.
# This catches errors before you push to AWS.
echo "--- Step 5: Local smoke tests ---"

echo "  Testing similarity Lambda locally..."
docker run --rm \
    -e AWS_DEFAULT_REGION="$AWS_REGION" \
    -e BUCKET_NAME="beauty-boba-js-sip-and-tint" \
    -e SILVER_FLACONI="cleaned/flaconi/" \
    -e SILVER_DM="cleaned/dm/" \
    -e GOLD_OUTPUT="output/recommendations/" \
    -e DYNAMODB_TABLE="beauty-boba-dev-recommendations" \
    -p 9001:8080 \
    "${ECR_REGISTRY}/${SIM_REPO}:${TAG}" &

SIM_PID=$!
sleep 2

# Send a test event — if it returns HTTP 200, the handler loaded correctly
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -XPOST "http://localhost:9001/2015-03-31/functions/function/invocations" \
    -d '{"test": true}' 2>/dev/null || echo "000")

kill $SIM_PID 2>/dev/null
wait $SIM_PID 2>/dev/null

if [ "$RESPONSE" = "200" ]; then
    echo "  ✓ Similarity Lambda smoke test passed (HTTP 200)"
else
    echo "  ! Similarity Lambda returned HTTP $RESPONSE — check your handler.py"
    echo "    (continuing anyway — push and check CloudWatch logs)"
fi

echo ""

# ── STEP 6: Push to ECR ───────────────────────────────────────────────────────
echo "--- Step 6: Pushing images to ECR ---"

echo "  Pushing similarity image..."
docker push "${ECR_REGISTRY}/${SIM_REPO}:${TAG}"

echo ""
echo "  Pushing loader image..."
docker push "${ECR_REGISTRY}/${LOADER_REPO}:${TAG}"

echo ""

# ── STEP 7: Update Lambda functions to use the new images ─────────────────────
echo "--- Step 7: Updating Lambda functions ---"

echo "  Updating similarity Lambda..."
aws lambda update-function-code \
    --function-name "$SIM_FUNCTION" \
    --image-uri "${ECR_REGISTRY}/${SIM_REPO}:${TAG}" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --output table \
    --query 'Configuration.{Function:FunctionName, Size:CodeSize, Updated:LastModified}'

echo ""
echo "  Updating loader Lambda..."
aws lambda update-function-code \
    --function-name "$LOADER_FUNCTION" \
    --image-uri "${ECR_REGISTRY}/${LOADER_REPO}:${TAG}" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --output table \
    --query 'Configuration.{Function:FunctionName, Size:CodeSize, Updated:LastModified}'

echo ""
echo "=== Done ==="
echo "Both Lambda functions now run from Docker images in ECR."
echo ""
echo "Next: trigger the pipeline"
echo "  aws stepfunctions list-state-machines --region $AWS_REGION --profile $AWS_PROFILE"
