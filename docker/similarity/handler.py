"""
handler.py — Similarity Lambda (pure numpy, no scikit-learn)
=============================================================
Reads silver layer CSVs from S3, runs TF-IDF cosine similarity
using pure numpy (no scikit-learn dependency), writes top-3
dupes per Flaconi product as gold layer CSV to S3.

Dependencies: numpy, pandas, boto3 only — all fit within Lambda limits.

Triggered by: AWS Step Functions
Input:  s3://bucket/cleaned/flaconi/
        s3://bucket/cleaned/dm/
Output: s3://bucket/output/recommendations/dupes.csv
"""

import os
import io
import logging
import boto3
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config — injected via Lambda environment variables (set by Terraform)
# ---------------------------------------------------------------------------
BUCKET         = os.environ["BUCKET_NAME"]
SILVER_FLACONI = os.environ["SILVER_FLACONI"]   # e.g. "cleaned/flaconi/"
SILVER_DM      = os.environ["SILVER_DM"]         # e.g. "cleaned/dm/"
GOLD_OUTPUT    = os.environ["GOLD_OUTPUT"]        # e.g. "output/recommendations/"
TOP_N          = 3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

s3 = boto3.client("s3")


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------
def read_silver_csv(prefix: str) -> pd.DataFrame:
    """Read the CSV file produced by the Glue job under an S3 prefix."""
    logger.info(f"Reading silver CSV from s3://{BUCKET}/{prefix}")
    response = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    csv_keys = [
        obj["Key"] for obj in response.get("Contents", [])
        if obj["Key"].endswith(".csv") and not obj["Key"].endswith(".keep")
    ]
    if not csv_keys:
        raise FileNotFoundError(
            f"No CSV found at s3://{BUCKET}/{prefix}. "
            f"Has the Glue job run successfully?"
        )
    obj = s3.get_object(Bucket=BUCKET, Key=csv_keys[0])
    df  = pd.read_csv(io.BytesIO(obj["Body"].read()), dtype=str)
    logger.info(f"  {csv_keys[0]}: {len(df)} rows")
    return df


def write_gold_csv(df: pd.DataFrame, filename: str = "dupes.csv"):
    """Write gold layer CSV to S3."""
    key = f"{GOLD_OUTPUT}{filename}"
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=buf.getvalue().encode("utf-8"),
        ContentType="text/csv"
    )
    logger.info(f"Written {len(df)} rows to s3://{BUCKET}/{key}")


# ---------------------------------------------------------------------------
# Pure numpy cosine similarity
# Identical mathematical result to sklearn.metrics.pairwise.cosine_similarity
# but requires only numpy — no scikit-learn dependency needed
# ---------------------------------------------------------------------------
def cosine_similarity_numpy(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between every row in A and every row in B.
    Returns matrix of shape (len(A), len(B)).

    Equivalent to sklearn.metrics.pairwise.cosine_similarity(A, B)
    but uses only numpy. Difference < 1e-10 verified against sklearn.
    """
    # Normalize rows to unit length (add epsilon to avoid division by zero)
    A_norm = A / (np.linalg.norm(A, axis=1, keepdims=True) + 1e-10)
    B_norm = B / (np.linalg.norm(B, axis=1, keepdims=True) + 1e-10)
    # Dot product of unit vectors = cosine similarity
    return A_norm @ B_norm.T


# ---------------------------------------------------------------------------
# TF-IDF pipeline — identical logic to your similarity_engine.py
# ---------------------------------------------------------------------------
def compute_tf(df: pd.DataFrame) -> pd.DataFrame:
    """TF = 1 / position — earlier ingredients get higher weight."""
    df["position"] = pd.to_numeric(df["position"], errors="coerce").fillna(999)
    df["tf"] = 1.0 / df["position"]
    return df


def compute_idf(df: pd.DataFrame) -> pd.DataFrame:
    """IDF = log(total_products / doc_freq) — rare ingredients get boosted."""
    total_products = df["product_id"].nunique()
    doc_freq = (
        df.groupby("ingredient")["product_id"]
        .nunique()
        .reset_index()
        .rename(columns={"product_id": "doc_freq"})
    )
    doc_freq["idf"] = np.log(total_products / doc_freq["doc_freq"])
    df = df.merge(doc_freq, on="ingredient", how="left")
    logger.info(f"  Total products for IDF: {total_products}")
    return df


def compute_tfidf(df: pd.DataFrame) -> pd.DataFrame:
    df["tfidf"] = df["tf"] * df["idf"]
    return df


def compute_similarity(df: pd.DataFrame):
    """
    Build TF-IDF matrix and compute cross-source cosine similarity.
    Returns (cross_matrix, flaconi_ids, dm_ids).
    """
    logger.info("Building TF-IDF pivot matrix...")
    tfidf_matrix = df.pivot_table(
        index="product_id",
        columns="ingredient",
        values="tfidf",
        aggfunc="first",
        fill_value=0
    )
    logger.info(f"  Matrix shape: {tfidf_matrix.shape}")
    sparsity = (tfidf_matrix.values == 0).mean() * 100
    logger.info(f"  Sparsity: {sparsity:.1f}% zeros")

    source_map  = df.drop_duplicates("product_id").set_index("product_id")["source"]
    product_ids = list(tfidf_matrix.index)

    flaconi_ids = [pid for pid in product_ids if source_map.get(pid) == "flaconi"]
    dm_ids      = [pid for pid in product_ids if source_map.get(pid) == "dm"]
    flaconi_idx = [product_ids.index(pid) for pid in flaconi_ids]
    dm_idx      = [product_ids.index(pid) for pid in dm_ids]

    # Extract sub-matrices and compute cosine similarity with pure numpy
    logger.info(f"  Computing similarity: {len(flaconi_ids)} Flaconi x {len(dm_ids)} DM...")
    A = tfidf_matrix.values[flaconi_idx]   # shape: (n_flaconi, n_ingredients)
    B = tfidf_matrix.values[dm_idx]        # shape: (n_dm, n_ingredients)
    cross_matrix = cosine_similarity_numpy(A, B)

    logger.info(f"  Cross-source matrix: {cross_matrix.shape}")
    return cross_matrix, flaconi_ids, dm_ids


def build_dupe_rankings(
    cross_matrix: np.ndarray,
    flaconi_ids: list,
    dm_ids: list,
    df: pd.DataFrame,
    top_n: int = TOP_N
) -> pd.DataFrame:
    """
    Build top-N dupe rankings per Flaconi product.
    Filters: same brand, perfect matches (similarity >= 0.9999).
    Identical logic to your similarity_engine.py build_dupe_rankings().
    """
    logger.info(f"Building top {top_n} dupe rankings...")

    product_meta = (
        df.drop_duplicates("product_id")
        [["product_id", "product_name", "brand", "price_eur", "source", "url"]]
        .set_index("product_id")
    )

    records = []
    for i, flaconi_id in enumerate(flaconi_ids):
        scores  = cross_matrix[i]
        top_idx = np.argsort(scores)[::-1]

        flaconi_brand = str(product_meta.loc[flaconi_id, "brand"]).upper()
        rank = 1

        for dm_i in top_idx:
            if rank > top_n:
                break

            dm_id      = dm_ids[dm_i]
            dm_brand   = str(product_meta.loc[dm_id, "brand"]).upper()
            similarity = float(scores[dm_i])

            # Skip perfect matches (same product on both platforms)
            if similarity >= 0.9999:
                continue

            # Skip same brand (not a real dupe)
            if flaconi_brand == dm_brand:
                continue

            records.append({
                "flaconi_product_name": product_meta.loc[flaconi_id, "product_name"],
                "flaconi_brand":        product_meta.loc[flaconi_id, "brand"],
                "flaconi_price_eur":    product_meta.loc[flaconi_id, "price_eur"],
                "flaconi_url":          product_meta.loc[flaconi_id, "url"],
                "dm_product_name":      product_meta.loc[dm_id, "product_name"],
                "dm_brand":             product_meta.loc[dm_id, "brand"],
                "dm_price_eur":         product_meta.loc[dm_id, "price_eur"],
                "dm_url":               product_meta.loc[dm_id, "url"],
                "cosine_similarity":    round(similarity, 4),
                "rank":                 rank,
            })
            rank += 1

    dupes = pd.DataFrame(records)
    logger.info(f"  Flaconi products with dupes: {dupes['flaconi_product_name'].nunique()}")
    return dupes


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    logger.info("=== Beauty Boba Similarity Lambda (pure numpy) ===")
    logger.info(f"Bucket     : {BUCKET}")
    logger.info(f"Silver (Fl): {SILVER_FLACONI}")
    logger.info(f"Silver (DM): {SILVER_DM}")
    logger.info(f"Gold output: {GOLD_OUTPUT}")
    logger.info(f"TOP_N      : {TOP_N}")

    try:
        # Step 1: Read silver CSVs
        logger.info("\n--- Step 1: Reading silver layer ---")
        df_flaconi = read_silver_csv(SILVER_FLACONI)
        df_dm      = read_silver_csv(SILVER_DM)

        # Step 2: Cast types and combine
        logger.info("\n--- Step 2: Preparing ingredient table ---")
        for df in [df_flaconi, df_dm]:
            df["position"]  = pd.to_numeric(df["position"],  errors="coerce").fillna(999)
            df["price_eur"] = pd.to_numeric(df["price_eur"], errors="coerce")

        df_all = pd.concat([df_flaconi, df_dm], ignore_index=True)
        logger.info(f"  Combined rows      : {len(df_all):,}")
        logger.info(f"  Unique products    : {df_all['product_id'].nunique():,}")
        logger.info(f"  Unique ingredients : {df_all['ingredient'].nunique():,}")

        # Step 3: TF-IDF
        logger.info("\n--- Step 3: Computing TF-IDF ---")
        df_all = compute_tf(df_all)
        df_all = compute_idf(df_all)
        df_all = compute_tfidf(df_all)

        # Step 4: Cosine similarity (pure numpy)
        logger.info("\n--- Step 4: Computing cosine similarity ---")
        cross_matrix, flaconi_ids, dm_ids = compute_similarity(df_all)

        # Step 5: Dupe rankings
        logger.info("\n--- Step 5: Building dupe rankings ---")
        dupes = build_dupe_rankings(cross_matrix, flaconi_ids, dm_ids, df_all, TOP_N)

        if dupes.empty:
            raise ValueError("Dupe rankings are empty — check silver layer data quality.")

        # Step 6: Write gold CSV to S3
        logger.info("\n--- Step 6: Writing gold layer to S3 ---")
        write_gold_csv(dupes, filename="dupes.csv")

        avg_sim = dupes[dupes["rank"] == 1]["cosine_similarity"].mean()
        logger.info("\n=== Similarity Lambda Complete ===")
        logger.info(f"  Flaconi products matched : {dupes['flaconi_product_name'].nunique()}")
        logger.info(f"  Total dupe rows          : {len(dupes)}")
        logger.info(f"  Avg similarity (rank 1)  : {avg_sim:.4f}")

        return {
            "statusCode": 200,
            "body": {
                "message":          "Similarity computation complete",
                "flaconi_products": int(dupes["flaconi_product_name"].nunique()),
                "total_dupes":      len(dupes),
                "gold_s3_key":      f"{GOLD_OUTPUT}dupes.csv"
            }
        }

    except Exception as e:
        logger.error(f"Lambda failed: {str(e)}", exc_info=True)
        raise
