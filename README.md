# Pearls AQI Predictor

An end-to-end data science, MLOps, and production deployment project for forecasting PM2.5 concentration and Air Quality Index for the Zafar Memon DHA reference location in Karachi.

The system automatically collects recent air-quality and weather data, generates a 72-hour PM2.5 forecast, converts predicted PM2.5 values into AQI information, identifies potentially hazardous conditions, publishes validated immutable artifacts, serves forecasts through FastAPI and Streamlit, and continuously monitors the deployed production pipeline.

The project was developed as part of the **10Pearls Shine Data Science Internship**.

---

## Table of Contents

- [Project Overview](#project-overview)
- [What the System Does](#what-the-system-does)
- [Production Architecture](#production-architecture)
- [Automated Production Workloads](#automated-production-workloads)
- [Forecasting Approach](#forecasting-approach)
- [AQI and Alert Generation](#aqi-and-alert-generation)
- [MLOps Architecture](#mlops-architecture)
- [Artifact Publication Model](#artifact-publication-model)
- [Production Monitoring](#production-monitoring)
- [Production Evidence](#production-evidence)
- [Repository Structure](#repository-structure)
- [Technology Stack](#technology-stack)
- [Getting Started](#getting-started)
- [Running Locally](#running-locally)
- [Docker Workflow](#docker-workflow)
- [Testing](#testing)
- [Azure Deployment](#azure-deployment)
- [Security and Reliability](#security-and-reliability)
- [Development Notebooks](#development-notebooks)
- [Project Status](#project-status)
- [Useful Commands](#useful-commands)

---

## Project Overview

Pearls AQI Predictor covers the complete lifecycle of a production-oriented data science system:

- air-quality source discovery and validation;
- historical PM2.5 collection;
- historical and forecast weather collection;
- canonical dataset creation;
- data-quality validation;
- exploratory data analysis;
- time-series feature engineering;
- chronological model evaluation;
- PM2.5 forecasting;
- model explainability;
- AQI conversion and alert generation;
- FastAPI serving;
- Streamlit visualization;
- Docker containerization;
- Azure Blob artifact publication;
- Azure Container Registry image management;
- Azure Container Apps deployment;
- Hopsworks feature-store integration;
- Hopsworks model-registry integration;
- automated feature synchronization;
- automated forecast publication;
- automated retraining evaluation;
- production-health monitoring;
- durable incident and notification state;
- staging and production isolation;
- immutable release validation.

The deployed production system generates and serves a validated **72-hour PM2.5-based AQI forecast** for the reference location.

---

## What the System Does

```text
Air-quality data
      +
Weather data
      │
      ▼
Feature engineering
      │
      ▼
PM2.5 prediction
      │
      ▼
72-hour forecast
      │
      ▼
AQI conversion
      │
      ▼
Alert evaluation
      │
      ▼
Artifact validation
      │
      ▼
Immutable publication
      │
      ▼
Azure Blob Storage
      │
      ▼
FastAPI
      │
      ▼
Streamlit Dashboard
```

In parallel, operational workloads continuously update features, evaluate retraining eligibility, and monitor the health of the production system.

---

# Production Architecture

The final deployment uses separate staging and production workloads while sharing selected Azure infrastructure to remain compatible with the Azure for Students subscription.

```text
                         Azure Subscription
                                │
               ┌────────────────┴────────────────┐
               │                                 │
               ▼                                 ▼

      rg-pearls-aqi-staging              rg-pearls-aqi-prod
               │                                 │
               │                         id-pearls-aqi-prod
               │                                 │
               ▼                                 │
     cae-pearls-aqi-staging                      │
       shared ACA runtime                        │
               │                                 │
       ┌───────┴────────┐                        │
       │                │                        │
       ▼                ▼                        │
   Staging          Production                   │
   workloads        workloads                    │
       │                │                        │
       └────────────────┴───────────────┬────────┘
                                        │
                                        ▼
                            Shared infrastructure
                                        │
                    ┌───────────────────┼──────────────────┐
                    │                   │                  │
                    ▼                   ▼                  ▼
            Azure Container        Azure Storage       Hopsworks
               Registry               Account
                    │                   │
                    │          ┌────────┴────────┐
                    │          │                 │
                    ▼          ▼                 ▼
             immutable     artifacts         artifacts-prod
              images       staging            production
```

### Why the Container Apps environment is shared

The Azure subscription used for this project allows only one Container Apps Environment.

Instead of deleting staging or changing subscriptions, the production architecture reuses the existing Container Apps Environment while preserving isolation through:

- separate resource groups;
- separate application names;
- separate job names;
- separate managed identities;
- separate runtime configuration;
- separate secret references;
- separate Blob containers;
- separate latest pointers.

This provides practical production isolation while staying within the subscription limits.

---

## Production Application Layer

The deployed production application consists of:

```text
Internet
   │
   ├───────────────────────────────────┐
   │                                   │
   ▼                                   ▼
Streamlit                          FastAPI
Container App                     Container App
   │                                   │
   └──────── HTTPS /api/v1 ───────────►│
                                       │
                                       ▼
                                artifacts-prod
```

### FastAPI

The API exposes endpoints for:

- liveness;
- readiness;
- forecast data;
- hourly forecast data;
- forecast summaries;
- alerts;
- active alerts;
- metadata;
- pipeline status.

The API dynamically materializes the latest validated production forecast from Azure Blob Storage.

### Streamlit

The dashboard communicates only with FastAPI.

It does not directly access:

- Azure Blob Storage;
- Hopsworks;
- the model registry;
- Azure credentials.

This keeps the presentation layer isolated from data-platform credentials.

---

# Automated Production Workloads

Four Azure Container Apps Jobs operate the production pipeline.

| Workload                | Azure Job                        | Schedule      |
| ----------------------- | -------------------------------- | ------------- |
| Feature synchronization | `job-pearls-aqi-features-prod`   | `15 * * * *`  |
| Forecast publication    | `job-pearls-aqi-forecast-prod`   | `0 */6 * * *` |
| Retraining evaluation   | `job-pearls-aqi-retraining-prod` | `30 3 * * *`  |
| Production monitoring   | `job-pearls-aqi-monitoring-prod` | `45 * * * *`  |

Azure Container Apps cron schedules are evaluated in UTC.

### Hourly feature synchronization

The feature job:

- collects the latest air-quality observations;
- collects required weather information;
- validates incoming records;
- generates production features;
- writes feature data to Hopsworks.

### Six-hour forecast publication

The forecast job:

- resolves the production model;
- loads current features;
- generates the 72-hour PM2.5 forecast;
- converts PM2.5 predictions into AQI;
- evaluates alert conditions;
- validates the artifact package;
- publishes an immutable run;
- advances the production latest pointer.

### Daily retraining evaluation

The retraining workflow:

- checks whether sufficient new training data are available;
- refreshes training data when appropriate;
- trains a candidate model when retraining criteria are met;
- evaluates the candidate against the current production model;
- only promotes a model when the promotion requirements pass.

A retraining execution may therefore successfully complete without replacing the production model.

### Hourly production monitoring

The monitoring workload checks:

- feature synchronization health;
- forecast publication health;
- retraining health;
- production forecast freshness;
- artifact validity;
- recent execution status.

Monitoring state is persisted as durable production artifacts.

---

# Forecasting Approach

The system forecasts PM2.5 for the next **72 hours**.

Feature engineering includes:

- lag features;
- rolling-window statistics;
- trend features;
- temperature;
- humidity;
- dew point;
- surface pressure;
- precipitation;
- cloud cover;
- visibility;
- wind speed;
- wind direction;
- wind gusts;
- cyclical time features.

Chronological train, validation, and test splits are used to prevent future information from leaking into model evaluation.

The final inference design combines persistence behavior where appropriate with the trained forecasting model for longer forecast horizons.

---

# AQI and Alert Generation

Predicted PM2.5 values are converted into indicative AQI information.

Each hourly forecast includes information such as:

- predicted PM2.5;
- indicative hourly AQI;
- AQI category;
- rolling 24-hour PM2.5;
- rolling 24-hour AQI;
- alert level;
- alert trigger;
- health message;
- recommended action.

The production API currently serves exactly:

```text
72 hourly forecast rows
```

for each successful forecast publication.

> The generated AQI information is intended for forecasting and demonstration purposes and is not an official regulatory AQI product.

---

# MLOps Architecture

The project supports both local development and remote MLOps services.

```text
                     Hopsworks
             ┌───────────┴───────────┐
             │                       │
             ▼                       ▼
       Feature Store            Model Registry
             │                       │
             └───────────┬───────────┘
                         │
                         ▼
                Production pipeline
                         │
                         ▼
                 AQI forecast artifacts
```

The system includes:

- feature-group validation;
- incremental feature updates;
- historical feature backfilling;
- training-dataset refresh;
- model registration;
- production-model resolution;
- candidate-versus-champion evaluation;
- controlled model promotion;
- remote model loading with fallback support.

---

# Artifact Publication Model

Forecast artifacts are never published directly into a mutable serving directory.

Each valid execution first creates an immutable run:

```text
aqi/runs/<run-id>/
├── alert_episodes.json
├── aqi_forecast_summary.json
├── aqi_metadata.json
├── live_pm25_aqi_forecast.parquet
├── manifest.json
└── phase_6_validation_report.json
```

The manifest records:

- artifact names;
- sizes;
- content types;
- SHA-256 checksums.

After the complete package passes validation, the serving pointer is updated:

```text
aqi/latest/pointer.json
```

The production storage boundary is:

```text
artifacts-prod
```

while staging uses:

```text
artifacts
```

This prevents staging forecast state from becoming production serving state.

---

## Publication Safety

The publication sequence is:

```text
Generate
   ↓
Validate
   ↓
Build manifest
   ↓
Upload immutable run
   ↓
Validate uploaded package
   ↓
Advance latest pointer
```

A failed or incomplete run therefore cannot automatically replace the previous valid forecast.

---

# Production Monitoring

Production-health snapshots are persisted under:

```text
production-health/runs/<run-id>/
```

The latest monitoring state is referenced through:

```text
production-health/latest/pointer.json
```

The system also maintains durable notification state:

```text
production-health/notifications/outbox.json
```

This supports:

- incident deduplication;
- durable pending notifications;
- delivery receipts;
- incident resolution tracking.

External notification delivery is intentionally treated as an operational integration rather than a requirement for forecast generation or serving availability.

---

# Production Release Model

API, dashboard, and pipeline images are built from a single release revision.

Images follow:

```text
walpole.azurecr.io/pearls-aqi/api:<git-sha>
walpole.azurecr.io/pearls-aqi/dashboard:<git-sha>
walpole.azurecr.io/pearls-aqi/pipeline:<git-sha>
```

No mutable `latest` tag is required for production deployment.

Each production image contains OCI metadata including:

- image title;
- application version;
- Git revision;
- build timestamp.

Runtime containers use non-root users.

The release validated during the final production deployment used:

```text
0d5380b79b54c1c333ce1fec4ebfbfe01bef8cc7
```

Subsequent documentation commits do not require rebuilding this locked release unless application code changes.

---

# Production Evidence

A curated set of generated validation reports is included in the repository under:

```text
reports/phase_10/
```

These reports provide machine-readable evidence of the deployed system state.

### Most important reports

| Report                                                  | Purpose                                                                            |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `production_deployment_validation_report.json`          | End-to-end validation of the complete deployed production system                   |
| `production_release_declaration.json`                   | Final release declaration, release SHA, endpoints, artifacts, and rollback anchors |
| `production_initial_publication_validation_report.json` | Verifies the first controlled production execution and AQI publication             |
| `production_jobs_validation_report.json`                | Validates all production scheduled jobs, images, schedules, and configuration      |
| `production_api_validation_report.json`                 | Validates the production FastAPI deployment                                        |
| `production_dashboard_validation_report.json`           | Validates the production Streamlit deployment                                      |
| `production_infrastructure_validation_report.json`      | Validates Azure infrastructure and production identity                             |
| `production_release_validation_report.json`             | Verifies immutable API, dashboard, and pipeline images                             |
| `production_monitoring_validation_report.json`          | Validates monitoring configuration and operational checks                          |
| `production_health_report.json`                         | Captures generated production-health state                                         |
| `artifact_repository_validation_report.json`            | Validates artifact repository behavior                                             |
| `forecast_publication_report.json`                      | Records forecast publication results                                               |
| `hourly_feature_job_report.json`                        | Records hourly feature-job validation                                              |
| `daily_retraining_job_report.json`                      | Records retraining workflow validation                                             |
| `registry_publication_report.json`                      | Records model-registry publication behavior                                        |

These files contain validation evidence and infrastructure metadata but do not intentionally contain secret values.

---

# Repository Structure

```text
pearls-aqi-predictor/
├── app/
│   ├── api/                    # FastAPI service
│   ├── core/                   # Shared configuration and utilities
│   ├── data_sources/           # Air-quality and weather clients
│   ├── inference/              # Model loading and inference
│   ├── mlops/                  # Hopsworks and registry integration
│   ├── operations/             # Monitoring and deployment validation
│   ├── pipelines/              # Production data and inference pipelines
│   └── storage/                # Local and Azure Blob repositories
│
├── dashboard/                  # Streamlit application
├── notebooks/                  # Phase-by-phase development notebooks
├── models/                     # Local/fallback model artifacts
├── aqi/                        # Local AQI artifacts
├── inference/                  # Local inference artifacts
│
├── reports/
│   └── phase_10/               # Curated production validation evidence
│
├── scripts/
│   ├── deployment utilities
│   ├── Azure job deployment
│   ├── image publication
│   └── operational validation
│
├── tests/                      # Automated tests
├── config/                     # Deployment configuration contracts
│
├── Dockerfile.api
├── Dockerfile.dashboard
├── Dockerfile.pipeline
├── compose.production.yml
├── compose.local-pipeline.yml
├── .env.production.example
├── pyproject.toml
├── uv.lock
└── README.md
```

---

# Technology Stack

## Data Science

- Python 3.12
- Pandas
- NumPy
- PyArrow
- Scikit-learn
- XGBoost
- Joblib
- SHAP
- Matplotlib
- Plotly

## Application

- FastAPI
- Uvicorn
- Pydantic Settings
- Streamlit
- Requests

## MLOps

- Hopsworks Feature Store
- Hopsworks Model Registry
- immutable model and artifact publication
- automated retraining evaluation
- candidate/champion model comparison

## Infrastructure

- Docker
- Docker Compose
- Azure Container Registry
- Azure Container Apps
- Azure Container Apps Jobs
- Azure Blob Storage
- Azure Managed Identity
- Azure CLI
- Git / GitHub
- `uv`

---

# Getting Started

## Prerequisites

Install:

- Python 3.12
- Git
- `uv`
- Docker
- Docker Compose
- Azure CLI for Azure operations

Check:

```bash
python3 --version
uv --version
docker --version
docker compose version
```

---

## Clone the Repository

```bash
git clone https://github.com/riyanj220/pearls-aqi-predictor.git
cd pearls-aqi-predictor
```

---

## Install Dependencies

```bash
uv sync --all-groups
```

Activate:

```bash
source .venv/bin/activate
```

Commands can also be run directly:

```bash
uv run python --version
```

---

# Environment Configuration

Example environment files are provided.

```text
.env.example
.env.api.example
.env.dashboard.example
.env.pipeline.example
.env.production.example
```

Create a local environment:

```bash
cp .env.example .env
```

Never commit real API keys, webhook URLs containing credentials, bearer tokens, Azure storage keys, or Hopsworks credentials.

### Local pipeline

```env
OPENAQ_API_KEY=replace-with-your-key

MODEL_LOADING_MODE=LOCAL_ARTIFACT
FEATURE_STORE_BACKEND=local
MODEL_REGISTRY_BACKEND=local

ARTIFACT_BACKEND=local
```

### Local API

```env
PEARLS_API_ARTIFACT_BACKEND=local
PEARLS_API_ARTIFACT_TYPE=aqi
PEARLS_API_PHASE_6_LATEST_DIRECTORY=aqi/latest
```

### Azure Blob API backend

```env
PEARLS_API_ARTIFACT_BACKEND=azure_blob
PEARLS_API_ARTIFACT_TYPE=aqi
PEARLS_API_AZURE_STORAGE_ACCOUNT=replace-with-storage-account
PEARLS_API_AZURE_STORAGE_CONTAINER=artifacts-prod
PEARLS_API_PHASE_6_BLOB_CACHE_DIRECTORY=.cache/api/aqi/latest
```

---

# Running Locally

## FastAPI

```bash
uv run uvicorn app.api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

Endpoints:

```text
http://localhost:8000
http://localhost:8000/docs
http://localhost:8000/redoc
```

Health:

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
```

Forecast:

```bash
curl http://localhost:8000/api/v1/forecast
```

---

## Streamlit Dashboard

```bash
uv run streamlit run dashboard/app.py \
  --server.address 0.0.0.0 \
  --server.port 8501
```

Open:

```text
http://localhost:8501
```

Configure the API:

```env
FASTAPI_BASE_URL=http://localhost:8000/api/v1
```

---

## Forecast Pipeline

Run live inference:

```bash
uv run python -m app.pipelines.live_inference
```

Generate AQI and alerts:

```bash
uv run python -m app.pipelines.aqi_alert_pipeline
```

Run the complete publication workflow:

```bash
uv run python -m app.pipelines.publish_forecast
```

---

# Docker Workflow

## Build Images

Use the full Git SHA for traceability:

```bash
export IMAGE_TAG="$(git rev-parse HEAD)"
```

API:

```bash
docker build \
  -f Dockerfile.api \
  -t "pearls-aqi-api:${IMAGE_TAG}" \
  .
```

Dashboard:

```bash
docker build \
  -f Dockerfile.dashboard \
  -t "pearls-aqi-dashboard:${IMAGE_TAG}" \
  .
```

Pipeline:

```bash
docker build \
  -f Dockerfile.pipeline \
  -t "pearls-aqi-pipeline:${IMAGE_TAG}" \
  .
```

---

## Docker Compose

Start API and dashboard:

```bash
docker compose \
  -f compose.production.yml \
  up -d api dashboard
```

Check:

```bash
docker compose \
  -f compose.production.yml \
  ps
```

Logs:

```bash
docker compose \
  -f compose.production.yml \
  logs -f api
```

Stop:

```bash
docker compose \
  -f compose.production.yml \
  down
```

---

## Run Pipeline with Docker Compose

```bash
docker compose \
  -f compose.production.yml \
  -f compose.local-pipeline.yml \
  --profile jobs \
  run --rm pipeline
```

---

# Testing

Run the complete suite:

```bash
uv run pytest -v
```

API:

```bash
uv run pytest tests/api -v
```

Dashboard:

```bash
uv run pytest tests/dashboard -v
```

---

# Azure Deployment

Production deployment is intentionally split into explicit, auditable steps.

Important deployment utilities include scripts for:

- infrastructure preparation;
- production API deployment;
- production dashboard deployment;
- production scheduled jobs;
- immutable image publication;
- controlled initial production execution.

Production resources include:

```text
rg-pearls-aqi-prod
├── id-pearls-aqi-prod
├── ca-pearls-aqi-api-prod
├── ca-pearls-aqi-dashboard-prod
├── job-pearls-aqi-features-prod
├── job-pearls-aqi-forecast-prod
├── job-pearls-aqi-retraining-prod
└── job-pearls-aqi-monitoring-prod
```

The applications and jobs run inside the shared:

```text
cae-pearls-aqi-staging
```

Container Apps Environment because of the subscription environment quota.

---

## Publish Immutable Images

Authenticate:

```bash
az acr login --name walpole
```

Set release:

```bash
export IMAGE_TAG="$(git rev-parse HEAD)"
```

Publish:

```bash
./scripts/publish_acr_images.sh
```

---

# Security and Reliability

## Managed Identity

Azure-hosted workloads use a user-assigned managed identity.

Typical roles include:

```text
AcrPull
Storage Blob Data Contributor
Reader
```

No Azure registry password or Blob storage key needs to be embedded into production images.

---

## Secret References

Sensitive values such as:

```text
OPENAQ_API_KEY
HOPSWORKS_API_KEY
PRODUCTION_HEALTH_WEBHOOK_URL
```

are injected at runtime through Azure Container Apps secret references.

Public validation reports may include secret **names** and `secretRef` identifiers but do not intentionally expose secret values.

---

## Non-root containers

Production images run with dedicated non-root users:

```text
API        → pearls
Dashboard  → dashboard
Pipeline   → pipeline
```

---

## Forecast Freshness

Production API thresholds are:

```text
0 – 7 hours     FRESH
7 – 13 hours    AGING
> 13 hours      STALE
```

This aligns with the six-hour forecast publication schedule while allowing reasonable execution tolerance.

---

## Failure and Recovery

The project validates that:

- failed forecast runs do not replace valid artifacts;
- the latest pointer remains unchanged after failed publication;
- the API continues serving the last valid forecast;
- successful recovery produces a new immutable run;
- the latest pointer advances only after validation;
- the API discovers recovered artifacts without redeployment.

---

# Development Notebooks

```text
00_openaq_source_discovery_and_validation.ipynb
01_open_meteo_source_validation.ipynb
02_build_canonical_dataset.ipynb
03_build_training_dataset.ipynb
04_train_baseline_models.ipynb
05_model_explainability.ipynb
06_live_inference_pipeline.ipynb
07_build_aqi_and_alerts.ipynb
08_build_fastapi_service.ipynb
09_build_streamlit_dashboard.ipynb
10_build_hopsworks_mlops_pipeline.ipynb
11_production_deployment_and_operations.ipynb
```

The notebooks document development and validation decisions.

Production execution is implemented in Python modules and deployment scripts rather than relying on notebooks.

---

# Project Status

The core project is **production deployed and operational**.

Completed areas include:

- [x] air-quality source discovery;
- [x] weather-source validation;
- [x] historical data collection;
- [x] canonical dataset creation;
- [x] data-quality validation;
- [x] feature engineering;
- [x] chronological model evaluation;
- [x] model explainability;
- [x] 72-hour PM2.5 inference;
- [x] AQI conversion;
- [x] alert generation;
- [x] FastAPI service;
- [x] Streamlit dashboard;
- [x] Docker production images;
- [x] Azure Container Registry;
- [x] Azure Blob artifact repository;
- [x] Hopsworks Feature Store;
- [x] Hopsworks Model Registry;
- [x] automated feature synchronization;
- [x] automated forecast publication;
- [x] automated retraining evaluation;
- [x] production-health monitoring;
- [x] durable monitoring snapshots;
- [x] incident deduplication;
- [x] notification outbox;
- [x] managed-identity authentication;
- [x] staging deployment;
- [x] production deployment;
- [x] immutable production release;
- [x] staging/production artifact isolation;
- [x] initial production publication;
- [x] end-to-end production validation;
- [x] production release declaration.

### Accepted operational constraints

The final deployment intentionally retains two documented constraints:

1. **Shared Container Apps Environment**
   Staging and production share one Azure Container Apps Environment because the Azure subscription allows only one environment.

2. **External notification delivery**
   Durable production-health monitoring and notification outbox persistence are implemented. Permanent external delivery is treated as an optional operational integration and does not block forecast generation, serving, or monitoring persistence.

---

# Useful Commands

### Start API

```bash
uv run uvicorn app.api.main:app --reload
```

### Start dashboard

```bash
uv run streamlit run dashboard/app.py
```

### Run complete forecast publication

```bash
uv run python -m app.pipelines.publish_forecast
```

### Run production deployment validator

```bash
uv run python -m \
  app.operations.production_deployment_validation \
  --release-sha "<production-release-sha>"
```

### Generate production release declaration

```bash
uv run python -m \
  app.operations.production_release_declaration \
  --release-sha "<production-release-sha>"
```

### Run tests

```bash
uv run pytest -v
```

### Inspect Docker usage

```bash
docker system df
```

### Remove unused build cache

```bash
docker builder prune
```

---

## Disclaimer

This project provides PM2.5 forecasting and indicative AQI information for educational, research, and engineering purposes.

It is not an official regulatory air-quality service and should not replace guidance issued by government or environmental authorities.
