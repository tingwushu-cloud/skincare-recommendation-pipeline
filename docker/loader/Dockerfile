# ── Loader Lambda ──────────────────────────────────────────────────────────────
FROM public.ecr.aws/lambda/python:3.11

COPY requirements.txt .

RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

COPY handler.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.lambda_handler"]
