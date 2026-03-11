# Sip and Tint — Skincare Dupe Finder

> Find affordable DM alternatives to expensive Flaconi skincare products using NLP ingredient matching.
---

## Project Summary

Sip and Tint scrapes ingredient lists from two German retailers — **Flaconi** (premium) and **DM** (drugstore) — and uses **TF-IDF cosine similarity** on INCI ingredient sequences to find the closest affordable dupes. The result is a searchable dashboard where users can find budget alternatives to luxury skincare.

- **809** Flaconi products × **560** DM products = **452,040** comparisons
- **771** dupe recommendations stored and served via DynamoDB
- Full AWS data pipeline from raw scrape to live dashboard

---

## Architecture

```
Scraping (Python)
    ↓
S3 (raw CSVs)
    ↓
AWS Glue (PySpark ETL)
    ↓
S3 (cleaned CSVs)
    ↓
Lambda: similarity (Docker / ECR)     ← TF-IDF cosine similarity
    ↓
S3 (dupes.csv)
    ↓
Lambda: loader (Docker / ECR)         ← loads to DynamoDB
    ↓
DynamoDB                              ← 771 recommendations
    ↓
Streamlit dashboard                   ← user-facing search
```

**Orchestration:** AWS Step Functions (triggered by EventBridge on S3 upload)

**Infrastructure:** All AWS resources provisioned with Terraform

---

## Tech Stack

| Layer | Technology |
|---|---|
| Scraping | Python (BeautifulSoup, Selenium) |
| Storage | AWS S3 |
| ETL | AWS Glue (PySpark) |
| Similarity Engine | Python (numpy, pandas, scikit-learn, scipy) |
| Containerisation | Docker + AWS ECR |
| Compute | AWS Lambda (image-type) |
| Database | AWS DynamoDB |
| Orchestration | AWS Step Functions + Apache Airflow |
| Infrastructure | Terraform |
| Alerting | AWS SNS |
| Frontend | Streamlit |
| CI/CD | GitHub Actions |

---

## Similarity Algorithm

The core engine uses **TF-IDF cosine similarity** on INCI ingredient lists:

**TF (Term Frequency)** — uses ingredient position as a concentration proxy:
```
TF = 1 / position
```
Ingredients listed first (highest concentration) score higher.

**IDF (Inverse Document Frequency)** — rewards rare active ingredients:
```
IDF = log(1332 / products_containing_ingredient)
```
Rare actives like Madecassoside (IDF: 6.09) score much higher than common bases like Aqua (IDF: 0.18).

**Result:** Top 5 DM dupes per Flaconi product, filtered to cross-brand matches only.

---

## Branches

### `main` — Core Pipeline

The base project built during the bootcamp.

**Setup:**
```bash
# Clone the repo
git clone https://github.com/tingwushu-cloud/skincare-recommendation-pipeline.git
cd skincare-recommendation-pipeline

# Install dependencies
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure AWS
aws configure --profile terraform-user

# Deploy infrastructure
cd infrastructure
terraform init
terraform apply -var-file=terraform.tfvars

# Run pipeline manually
AWS_PROFILE=terraform-user aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:eu-central-1:444398957152:stateMachine:beauty-boba-dev-pipeline
```

**Run the dashboard:**
```bash
AWS_PROFILE=terraform-user streamlit run dashboard/app_v7.py
```

---

### `feature/docker-airflow` — Docker Containerisation + Airflow

Extends the core pipeline with Docker-based Lambda deployment and Apache Airflow orchestration.

**What's added:**
- Both Lambda functions packaged as Docker images and deployed via AWS ECR
- Apache Airflow DAG replacing Step Functions as the orchestrator
- GitHub Actions workflow for automated Docker build and ECR push on code change

**Why Docker?**
Lambda zip deployments have a 250MB limit and platform-specific binary issues. Docker images solve both — built for `linux/amd64`, tested locally before deploying to AWS.

**Run Airflow locally:**
```bash
cd airflow/
docker-compose build
docker-compose run --rm airflow-init
docker-compose up -d
# UI at http://localhost:8080 (airflow / airflow)
```

**Airflow DAG:**
```
run_glue_bronze_to_silver
    ↓
wait_for_glue (polls every 60s)
    ↓
run_similarity_lambda
    ↓
run_loader_lambda
    ↓
verify_dynamodb
```

**Rebuild and redeploy Lambda images:**
```bash
# Build and push similarity image
docker build --platform linux/amd64 --provenance=false \
  -t 444398957152.dkr.ecr.eu-central-1.amazonaws.com/beauty-boba-similarity:latest \
  docker/similarity/
docker push 444398957152.dkr.ecr.eu-central-1.amazonaws.com/beauty-boba-similarity:latest

# Update Lambda
aws lambda update-function-code \
  --function-name beauty-boba-dev-similarity \
  --image-uri 444398957152.dkr.ecr.eu-central-1.amazonaws.com/beauty-boba-similarity:latest \
  --region eu-central-1
```

---

### `feature/dbt-redshift` — dbt Transformations on Redshift

Adds a dbt transformation layer on top of Amazon Redshift Serverless, replacing the Glue ETL for the cleaning step.

**What's added:**
- Amazon Redshift Serverless provisioned via Terraform
- Raw CSVs loaded from S3 into Redshift bronze schema
- dbt staging models (views) for light cleaning
- dbt silver models (tables) for enriched, query-ready data
- dbt data quality tests (8 tests, all passing)
- dbt lineage documentation

**Why dbt?**
dbt brings software engineering practices to SQL — version control, testing, documentation, and lineage graphs. Every transformation is a `.sql` file tracked in Git.

**Run dbt:**
```bash
cd dbt/skincare
source ../../venv/bin/activate

# Test connection
dbt debug

# Run all models
dbt run

# Run tests
dbt test

# Generate and view lineage docs
dbt docs generate
dbt docs serve
# Open http://localhost:8080
```

**dbt model structure:**
```
models/
  staging/
    stg_dm_products.sql         ← view: light cleaning on DM raw data
    stg_flaconi_products.sql    ← view: join products + ingredients
    schema.yml                  ← data quality tests
  silver/
    dm_products.sql             ← table: cleaned DM products
    flaconi_products.sql        ← table: cleaned Flaconi products
```

**Data lineage:**
```
bronze.dm_raw
    → stg_dm_products (view)
        → dm_products (table)

bronze.flaconi_products_raw + bronze.flaconi_ingredients_raw
    → stg_flaconi_products (view)
        → flaconi_products (table)
```

---

## Project Structure

```
skincare-recommendation-pipeline/
  dashboard/
    app_v7.py                   ← Streamlit frontend
  docker/
    similarity/                 ← Dockerfile + requirements for similarity Lambda
    loader/                     ← Dockerfile + requirements for loader Lambda
  airflow/
    dags/
      sip_and_tint_pipeline.py  ← Airflow DAG
    docker-compose.yml
    Dockerfile
  dbt/
    skincare/
      models/
        staging/
        silver/
      setup/
        load_raw_tables.sql     ← one-time S3 to Redshift load
  infrastructure/
    main.tf
    variables.tf
    modules/
      s3/ glue/ lambda/ dynamodb/
      step_functions/ iam/ sns/
      eventbridge/ redshift/
  lambda/
    similarity/
      handler.py
    loader/
      handler.py
  glue/
    bronze_to_silver.py
```

---

## Environment Setup

**Required AWS resources** (all created by Terraform):
- S3 bucket: `beauty-boba-js-sip-and-tint`
- Glue job: `beauty-boba-dev-bronze-to-silver`
- Lambda: `beauty-boba-dev-similarity`, `beauty-boba-dev-loader`
- DynamoDB: `beauty-boba-dev-recommendations`
- ECR: `beauty-boba-similarity`, `beauty-boba-loader`
- Redshift Serverless: `beauty-boba-dev` (feature/dbt-redshift branch only)

**Required files (not committed):**
```
infrastructure/terraform.tfvars     ← AWS credentials and config
airflow/.env                        ← AWS credentials for Airflow
~/.dbt/profiles.yml                 ← dbt Redshift connection
```

---

## Authors

Emily Tran — [tran.ngoc.eb@gmail.com](mailto:tran.ngoc.eb@gmail.com)
Joseph Shu — [tingwushu@gmail.com](mailto:tingwushu@gmail.com)


*This branch (feature/docker-airflow and feature/dbt-redshift) is my individual extension of the team project. Core pipeline by Emi Tran and Joseph Shu.*
