-- setup/load_raw_tables.sql
-- Run this once to load raw CSVs from S3 into Redshift

-- ── Create schema ──────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS bronze;

-- ── DM products table ──────────────────────────────────────
DROP TABLE IF EXISTS bronze.dm_raw;
CREATE TABLE bronze.dm_raw (
    product_url   VARCHAR(1000),
    price         VARCHAR(50),
    base_price    VARCHAR(200),
    rating        VARCHAR(20),
    review_count  VARCHAR(20),
    ingredients   VARCHAR(MAX),
    subcategory   VARCHAR(200),
    brand         VARCHAR(200),
    product_name  VARCHAR(500),
    gtin          VARCHAR(50),
    image_url     VARCHAR(1000)
);

COPY bronze.dm_raw
FROM 's3://beauty-boba-js-sip-and-tint/raw/dm/dm_final.csv'
IAM_ROLE 'arn:aws:iam::444398957152:role/beauty-boba-dev-redshift-role'
FORMAT AS CSV
DELIMITER ','
QUOTE '"'
IGNOREHEADER 1
REGION 'eu-central-1';

-- ── Flaconi products table ─────────────────────────────────
DROP TABLE IF EXISTS bronze.flaconi_products_raw;
CREATE TABLE bronze.flaconi_products_raw (
    brand         VARCHAR(200),
    series        VARCHAR(500),
    product_type  VARCHAR(200),
    price         VARCHAR(50),
    uvp_price     VARCHAR(50),
    base_price    VARCHAR(200),
    url           VARCHAR(1000)
);

COPY bronze.flaconi_products_raw
FROM 's3://beauty-boba-js-sip-and-tint/raw/flaconi/flaconi_gesichtscreme.csv'
IAM_ROLE 'arn:aws:iam::444398957152:role/beauty-boba-dev-redshift-role'
FORMAT AS CSV
DELIMITER ';'
QUOTE '"'
IGNOREHEADER 1
REGION 'eu-central-1';

-- ── Flaconi ingredients table ──────────────────────────────
DROP TABLE IF EXISTS bronze.flaconi_ingredients_raw;
CREATE TABLE bronze.flaconi_ingredients_raw (
    url           VARCHAR(1000),
    brand         VARCHAR(200),
    product_name  VARCHAR(500),
    ingredients   VARCHAR(MAX)
);

COPY bronze.flaconi_ingredients_raw
FROM 's3://beauty-boba-js-sip-and-tint/raw/flaconi/flaconi_ingredients.csv'
IAM_ROLE 'arn:aws:iam::444398957152:role/beauty-boba-dev-redshift-role'
FORMAT AS CSV
DELIMITER ','
QUOTE '"'
IGNOREHEADER 1
REGION 'eu-central-1';

-- ── Verify row counts ──────────────────────────────────────
SELECT 'dm_raw'                  AS table_name, COUNT(*) AS rows FROM bronze.dm_raw
UNION ALL
SELECT 'flaconi_products_raw'    AS table_name, COUNT(*) AS rows FROM bronze.flaconi_products_raw
UNION ALL
SELECT 'flaconi_ingredients_raw' AS table_name, COUNT(*) AS rows FROM bronze.flaconi_ingredients_raw;
