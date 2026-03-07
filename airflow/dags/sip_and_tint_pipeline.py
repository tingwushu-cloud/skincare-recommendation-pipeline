"""
sip_and_tint_pipeline.py
========================
Airflow DAG that orchestrates the full Sip and Tint pipeline:

    [Glue: bronze → silver]
         ↓
    [Lambda: similarity engine → dupes.csv]
         ↓
    [Lambda: loader → DynamoDB]
         ↓
    [Verify: DynamoDB item count]

This DAG replaces Step Functions as the orchestrator.
The actual processing still happens in AWS — Airflow just triggers
and monitors each step.

Schedule: weekly on Monday at 07:00 Berlin time
Manual run: toggle the DAG on in the Airflow UI and click "Trigger DAG"
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.amazon.aws.operators.glue import GlueJobOperator
from airflow.providers.amazon.aws.sensors.glue import GlueJobSensor
from airflow.providers.amazon.aws.operators.lambda_function import LambdaInvokeFunctionOperator
from airflow.providers.amazon.aws.hooks.dynamodb import DynamoDBHook
from airflow.operators.python import PythonOperator

# ── CONFIG ────────────────────────────────────────────────────────────────────
AWS_CONN_ID        = "aws_default"           # configured in Airflow UI → Connections
AWS_REGION         = "eu-central-1"
GLUE_JOB_NAME      = "beauty-boba-dev-bronze-to-silver"
SIMILARITY_LAMBDA  = "beauty-boba-dev-similarity"
LOADER_LAMBDA      = "beauty-boba-dev-loader"
DYNAMODB_TABLE     = "beauty-boba-dev-recommendations"

# ── DEFAULT ARGS ──────────────────────────────────────────────────────────────
default_args = {
    "owner": "sip-and-tint",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# ── HELPER: verify DynamoDB was populated ─────────────────────────────────────
def verify_dynamodb(**context):
    import boto3
    client = boto3.client('dynamodb', region_name=AWS_REGION)
    
    response = client.scan(
        TableName=DYNAMODB_TABLE,
        Select='COUNT'
    )
    item_count = response['Count']
    
    print(f"DynamoDB table '{DYNAMODB_TABLE}' has {item_count} items")
    
    if item_count == 0:
        raise ValueError(
            f"DynamoDB table is empty after loader ran. "
            f"Check CloudWatch logs for {LOADER_LAMBDA}."
        )
    
    print(f"✓ Pipeline complete — {item_count} recommendations in DynamoDB")
    return item_count


# ── DAG DEFINITION ────────────────────────────────────────────────────────────
with DAG(
    dag_id="sip_and_tint_pipeline",
    description="Weekly pipeline: Glue → similarity Lambda → loader Lambda → DynamoDB",
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule="0 7 * * 1",   # every Monday at 07:00
    catchup=False,                    # don't backfill missed runs
    tags=["sip-and-tint", "skincare", "etl"],
) as dag:

    # ── Task 1: Run Glue job (bronze → silver) ────────────────────────────────
    # Triggers the Glue job that cleans raw CSV files and writes to S3 silver layer.
    # script_location points to the bronze_to_silver.py you uploaded to S3.
    run_glue = GlueJobOperator(
    task_id="run_glue_bronze_to_silver",
    job_name=GLUE_JOB_NAME,
    aws_conn_id=AWS_CONN_ID,
    region_name=AWS_REGION,
    wait_for_completion=False,
    iam_role_name="beauty-boba-dev-glue-role",
    script_args={
        "--SOURCE_BUCKET": "beauty-boba-js-sip-and-tint",
        "--SOURCE_FLACONI_PRODUCTS": "raw/flaconi/flaconi_gesichtscreme.csv",
        "--SOURCE_FLACONI_INGREDIENTS": "raw/flaconi/flaconi_ingredients.csv",
        "--SOURCE_DM": "raw/dm/dm_final.csv",
        "--TARGET_FLACONI": "cleaned/flaconi/",
        "--TARGET_DM": "cleaned/dm/",
    },
)

    # ── Task 2: Wait for Glue to finish ───────────────────────────────────────
    # GlueJobSensor polls every 60 seconds until the job succeeds or fails.
    # This keeps Airflow's task log clean — you see each poll attempt.
    wait_for_glue = GlueJobSensor(
        task_id="wait_for_glue",
        job_name=GLUE_JOB_NAME,
        run_id="{{ task_instance.xcom_pull(task_ids='run_glue_bronze_to_silver', key='return_value') }}",
        aws_conn_id=AWS_CONN_ID,
        poke_interval=60,    # check every 60 seconds
        timeout=3600,        # give up after 1 hour
    )

    # ── Task 3: Invoke similarity Lambda ─────────────────────────────────────
    # Reads cleaned CSVs from S3 silver layer, runs TF-IDF cosine similarity,
    # writes dupes.csv to S3 gold layer.
    run_similarity = LambdaInvokeFunctionOperator(
        task_id="run_similarity_lambda",
        function_name=SIMILARITY_LAMBDA,
        aws_conn_id=AWS_CONN_ID,
        region_name=AWS_REGION,
        # Empty payload — Lambda reads its config from environment variables
        payload="{}",
        # Lambda timeout is 5 minutes; Airflow will wait for the response
    )

    # ── Task 4: Invoke loader Lambda ──────────────────────────────────────────
    # Reads dupes.csv from S3 gold layer, writes each row to DynamoDB.
    run_loader = LambdaInvokeFunctionOperator(
        task_id="run_loader_lambda",
        function_name=LOADER_LAMBDA,
        aws_conn_id=AWS_CONN_ID,
        region_name=AWS_REGION,
        payload="{}",
    )

    # ── Task 5: Verify DynamoDB was populated ─────────────────────────────────
    # A simple sanity check — confirms the loader actually wrote items.
    # If DynamoDB is empty, this task fails and you get a clear error.
    verify = PythonOperator(
        task_id="verify_dynamodb",
        python_callable=verify_dynamodb,
    )

    # ── Task dependencies (the pipeline order) ────────────────────────────────
    # run_glue → wait_for_glue → run_similarity → run_loader → verify
    run_glue >> wait_for_glue >> run_similarity >> run_loader >> verify
