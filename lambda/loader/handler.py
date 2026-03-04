"""
handler.py — Loader Lambda
===========================
Reads the gold layer dupes.csv from S3 and loads it into DynamoDB.

DynamoDB item structure (one item per Flaconi product):
{
    "flaconi_product_name": "Ultra Facial Cream",   <- partition key
    "flaconi_brand":        "Kiehl's",
    "flaconi_price_eur":    22.0,
    "flaconi_url":          "https://...",
    "top_matches": [
        {
            "rank":               1,
            "dm_product_name":    "Feuchtigkeitscreme",
            "dm_brand":           "Balea",
            "dm_price_eur":       2.95,
            "dm_url":             "https://...",
            "cosine_similarity":  0.8432
        },
        ...  (up to TOP_N matches)
    ]
}

Triggered by: AWS Step Functions (after similarity Lambda)
Input:  s3://bucket/output/recommendations/dupes.csv
Output: DynamoDB table beauty-boba-dev-recommendations
"""

import os
import io
import json
import logging
import boto3
import pandas as pd
from decimal import Decimal
from boto3.dynamodb.conditions import Key

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BUCKET         = os.environ["BUCKET_NAME"]
GOLD_OUTPUT    = os.environ["GOLD_OUTPUT"]       # e.g. "output/recommendations/"
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]    # e.g. "beauty-boba-dev-recommendations"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

s3       = boto3.client("s3")
dynamodb = boto3.resource("dynamodb", region_name="eu-central-1")
table    = dynamodb.Table(DYNAMODB_TABLE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def float_to_decimal(val):
    """
    DynamoDB does not accept Python floats — must use Decimal.
    Handles None/NaN gracefully.
    """
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return Decimal(str(round(float(val), 4)))
    except Exception:
        return None


def read_gold_csv() -> pd.DataFrame:
    """Read dupes.csv from S3 gold layer."""
    key = f"{GOLD_OUTPUT}dupes.csv"
    logger.info(f"Reading gold CSV from s3://{BUCKET}/{key}")
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    df  = pd.read_csv(io.BytesIO(obj["Body"].read()), dtype=str)
    logger.info(f"  Rows: {len(df)}")
    return df


def build_dynamodb_items(dupes: pd.DataFrame) -> list:
    """
    Group dupe rows by flaconi_product_name and build
    one DynamoDB item per Flaconi product with nested top_matches list.
    """
    items = []

    for flaconi_product, group in dupes.groupby("flaconi_product_name"):
        # Get Flaconi product metadata from first row
        first = group.iloc[0]

        # Build sorted top_matches list
        top_matches = []
        for _, row in group.sort_values("rank").iterrows():
            match = {
                "rank":              int(row["rank"]),
                "dm_product_name":   str(row["dm_product_name"]),
                "dm_brand":          str(row["dm_brand"]),
                "dm_price_eur":      float_to_decimal(row["dm_price_eur"]),
                "dm_url":            str(row["dm_url"]),
                "cosine_similarity": float_to_decimal(row["cosine_similarity"]),
            }
            top_matches.append(match)

        item = {
            # Partition key — must match DynamoDB table definition
            "flaconi_product_name": str(flaconi_product),
            # Flaconi product metadata
            "flaconi_brand":        str(first["flaconi_brand"]),
            "flaconi_price_eur":    float_to_decimal(first["flaconi_price_eur"]),
            "flaconi_url":          str(first["flaconi_url"]),
            # Nested recommendations list
            "top_matches":          top_matches,
        }
        items.append(item)

    logger.info(f"  Built {len(items)} DynamoDB items")
    return items


def load_to_dynamodb(items: list):
    """
    Batch write all items to DynamoDB.
    Uses batch_writer for efficiency — handles retries automatically.
    Clears existing items first to avoid stale data.
    """
    logger.info(f"Loading {len(items)} items into DynamoDB table: {DYNAMODB_TABLE}")

    # Scan existing items and delete them first (full refresh)
    logger.info("  Clearing existing items...")
    existing = table.scan(ProjectionExpression="flaconi_product_name")
    with table.batch_writer() as batch:
        for old_item in existing.get("Items", []):
            batch.delete_item(Key={"flaconi_product_name": old_item["flaconi_product_name"]})
    logger.info(f"  Cleared {len(existing.get('Items', []))} existing items")

    # Write new items in batches
    logger.info("  Writing new items...")
    success_count = 0
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
            success_count += 1

    logger.info(f"  Successfully written: {success_count} items")
    return success_count


def verify_load(expected_count: int):
    """Quick verification — count items in table after load."""
    response = table.scan(Select="COUNT")
    actual = response["Count"]
    logger.info(f"  Verification: expected {expected_count}, found {actual} items in DynamoDB")
    if actual < expected_count:
        raise ValueError(
            f"Load verification failed: expected {expected_count} items "
            f"but only found {actual} in DynamoDB table {DYNAMODB_TABLE}"
        )
    return actual


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    logger.info("=== Beauty Boba Loader Lambda ===")
    logger.info(f"Bucket         : {BUCKET}")
    logger.info(f"Gold output    : {GOLD_OUTPUT}")
    logger.info(f"DynamoDB table : {DYNAMODB_TABLE}")

    try:
        # Step 1: Read gold layer CSV from S3
        logger.info("\n--- Step 1: Reading gold layer from S3 ---")
        dupes = read_gold_csv()

        if dupes.empty:
            raise ValueError("Gold layer dupes.csv is empty — similarity Lambda may have failed.")

        # Step 2: Cast numeric columns
        logger.info("\n--- Step 2: Casting numeric columns ---")
        for col in ["rank", "cosine_similarity", "flaconi_price_eur", "dm_price_eur"]:
            dupes[col] = pd.to_numeric(dupes[col], errors="coerce")

        logger.info(f"  Flaconi products : {dupes['flaconi_product_name'].nunique()}")
        logger.info(f"  Total dupe rows  : {len(dupes)}")

        # Step 3: Build DynamoDB items
        logger.info("\n--- Step 3: Building DynamoDB items ---")
        items = build_dynamodb_items(dupes)

        # Step 4: Load to DynamoDB
        logger.info("\n--- Step 4: Loading to DynamoDB ---")
        success_count = load_to_dynamodb(items)

        # Step 5: Verify
        logger.info("\n--- Step 5: Verifying load ---")
        actual_count = verify_load(success_count)

        logger.info("\n=== Loader Lambda Complete ===")
        logger.info(f"  Items loaded     : {success_count}")
        logger.info(f"  Items verified   : {actual_count}")

        return {
            "statusCode": 200,
            "body": {
                "message":        "DynamoDB load complete",
                "items_loaded":   success_count,
                "items_verified": actual_count,
                "dynamodb_table": DYNAMODB_TABLE,
            }
        }

    except Exception as e:
        logger.error(f"Loader Lambda failed: {str(e)}", exc_info=True)
        raise
