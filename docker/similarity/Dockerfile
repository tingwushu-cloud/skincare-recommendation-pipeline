# ── Similarity Lambda ──────────────────────────────────────────────────────────
# Uses AWS's official Lambda base image for Python 3.11
# This ensures the runtime environment exactly matches what runs on AWS

FROM public.ecr.aws/lambda/python:3.11

# Copy requirements first — Docker caches this layer separately
# so a code-only change won't re-run pip install
COPY requirements.txt .

# Install dependencies into the Lambda task root
# --no-cache-dir keeps the image smaller
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# Copy the handler code
COPY handler.py ${LAMBDA_TASK_ROOT}/

# Tell Lambda which function to invoke
CMD ["handler.lambda_handler"]
