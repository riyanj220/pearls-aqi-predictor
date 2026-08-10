# Pearls AQI Predictor

An end-to-end data science, MLOps, and production deployment project for forecasting PM2.5 concentration and Air Quality Index for the Zafar Memon DHA reference location in Karachi.

The system automatically collects recent air-quality and weather data, maintains production features, generates a validated 72-hour PM2.5 forecast, converts predictions into AQI information, evaluates alert conditions, publishes immutable artifacts, serves results through FastAPI and Streamlit, evaluates retraining opportunities, and continuously monitors production health.

The project was developed as part of the **10Pearls Shine Data Science Internship**.

---

## Table of Contents

- [Project Overview](#project-overview)
- [System Flow](#system-flow)
- [Production Architecture](#production-architecture)
- [Automated Production Workloads](#automated-production-workloads)
- [Forecasting and AQI](#forecasting-and-aqi)
- [MLOps Architecture](#mlops-architecture)
- [Hopsworks to Azure Blob Migration](#hopsworks-to-azure-blob-migration)
- [Artifact Publication](#artifact-publication)
- [Production Monitoring](#production-monitoring)
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

---

## Project Overview

Pearls AQI Predictor covers the complete lifecycle of a production-oriented forecasting system:

- air-quality source discovery and validation;
- historical PM2.5 and weather collection;
- canonical dataset creation;
- data-quality validation;
- exploratory analysis;
- time-series feature engineering;
- chronological model evaluation;
- PM2.5 forecasting;
- model explainability;
- AQI conversion and alert generation;
- FastAPI serving;
- Streamlit visualization;
- Docker containerization;
- Azure Blob feature and artifact storage;
- Blob-backed model registry;
- Azure Container Registry image management;
- Azure Container Apps deployment;
- scheduled feature synchronization;
- scheduled forecast publication;
- automated retraining evaluation;
- production-health monitoring;
- durable incident and notification state;
- staging and production isolation;
- immutable release validation.

The deployed system serves a validated **72-hour PM2.5-based AQI forecast** for the reference location.

---

# System Flow

```text
OpenAQ PM2.5
      +
Weather data
      │
      ▼
Azure Blob Feature Store
      │
      ▼
Feature engineering
      │
      ▼
Production model
Azure Blob Model Registry
      │
      ▼
72-hour PM2.5 forecast
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
      ├──────────────► FastAPI
      │                    │
      │                    ▼
      └──────────────► Streamlit
```

In parallel:

```text
Scheduled feature updates
Scheduled retraining evaluation
Scheduled production monitoring
          │
          ▼
Azure Blob + Azure ARM
          │
          ▼
Durable health state
          │
          ▼
Azure Communication Services Email
```

---

# Production Architecture

Production workloads run in a dedicated production resource group while reusing the existing Container Apps Environment required by the Azure for Students subscription.

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
     cae-pearls-aqi-staging ◄────────────────────┘
      shared ACA environment
               │
       ┌───────┴─────────────────────────────┐
       │                                     │
       ▼                                     ▼
   Staging                              Production
   workloads                            workloads
                                             │
                     ┌───────────────────────┼───────────────────────┐
                     │                       │                       │
                     ▼                       ▼                       ▼
             Azure Container          Azure Blob              Azure ARM
                Registry                Storage                monitoring
                                             │
                              ┌──────────────┴──────────────┐
                              │                             │
                              ▼                             ▼
                         artifacts                     artifacts-prod
                          staging                       production
```

Production state is isolated through:

- separate resource groups;
- separate application and job names;
- a dedicated production managed identity;
- production-specific configuration;
- separate secret references;
- separate Blob containers;
- separate latest pointers.

The shared Container Apps Environment is an infrastructure constraint, not a shared application state boundary.

---

## Production Application Layer

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
- latest forecast;
- hourly forecast data;
- forecast summaries;
- alerts;
- active alerts;
- metadata;
- pipeline status.

The API materializes the latest validated forecast from Azure Blob Storage and does not perform model inference on request.

### Streamlit

The dashboard communicates with FastAPI rather than directly accessing storage or MLOps infrastructure.

It therefore does not require:

- Azure Blob credentials;
- model-registry access;
- feature-store access;
- Hopsworks credentials.

---

# Automated Production Workloads

Four Azure Container Apps Jobs operate the production pipeline.

| Workload                | Azure Job                        | Schedule      |
| ----------------------- | -------------------------------- | ------------- |
| Feature synchronization | `job-pearls-aqi-features-prod`   | `15 * * * *`  |
| Forecast publication    | `job-pearls-aqi-forecast-prod`   | `0 */6 * * *` |
| Retraining evaluation   | `job-pearls-aqi-retraining-prod` | `30 3 * * *`  |
| Production monitoring   | `job-pearls-aqi-monitoring-prod` | `45 * * * *`  |

Container Apps cron schedules are evaluated in UTC.

### Hourly feature synchronization

The feature job:

- fetches recent PM2.5 observations;
- fetches required weather information;
- validates incoming records;
- generates engineered features;
- incrementally updates the production Azure Blob feature repository.

Production datasets include:

```text
feature-store/
├── pm25_hourly_observations/
├── weather_hourly_observations/
└── pm25_hourly_features/
```

### Six-hour forecast publication

The forecast job:

- reads current features from Azure Blob;
- resolves the production model from the Azure Blob model registry;
- generates the 72-hour PM2.5 forecast;
- converts predictions into AQI;
- evaluates alert conditions;
- validates the complete package;
- publishes an immutable run;
- atomically advances the production latest pointer.

### Daily retraining evaluation

The retraining workflow:

- evaluates whether sufficient new training data exist;
- reads training features from Azure Blob;
- trains a candidate when retraining criteria are met;
- compares candidate and production models;
- registers/promotes a model only when promotion requirements pass.

A successful retraining execution does **not** imply that the production model changed.

### Hourly production monitoring

The monitoring job checks:

- Azure Container Apps Job execution health;
- feature freshness;
- forecast freshness;
- retraining status;
- publication validity;
- artifact availability.

Monitoring state and notification delivery records are durably persisted to Azure Blob Storage.

---

# Forecasting and AQI

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

Chronological train, validation, and test splits are used to avoid future-information leakage.

The inference strategy combines recent persistence behavior where appropriate with the trained forecasting model for longer forecast horizons.

Predicted PM2.5 values are converted into indicative AQI information.

Each hourly forecast includes:

- predicted PM2.5;
- indicative hourly AQI;
- AQI category;
- rolling 24-hour PM2.5;
- rolling 24-hour AQI;
- alert level;
- alert trigger;
- health message;
- recommended action.

A valid production publication contains exactly:

```text
72 hourly forecast rows
```

> AQI values are model-generated forecasting outputs and are not an official regulatory AQI product.

---

# MLOps Architecture

The application uses backend abstractions rather than binding pipeline logic directly to one external MLOps provider.

```text
                  Feature Repository
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
     Azure Blob                    Hopsworks
     production                 optional/demo
          │
          └──────────────┬──────────────┘
                         │
                         ▼
                  Feature pipeline


                    Model Registry
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
     Azure Blob                    Hopsworks
     production                 optional/demo
          │
          └──────────────┬──────────────┘
                         │
                         ▼
                 Forecast / Retraining
```

Supported feature-store backends include:

```text
FEATURE_STORE_BACKEND=azure_blob
FEATURE_STORE_BACKEND=hopsworks
```

Supported model-registry backends include:

```text
MODEL_REGISTRY_BACKEND=azure_blob
MODEL_REGISTRY_BACKEND=hopsworks
```

Production uses:

```text
FEATURE_STORE_BACKEND=azure_blob
MODEL_REGISTRY_BACKEND=azure_blob
MODEL_LOADING_MODE=AZURE_BLOB_REGISTRY
```

Hopsworks remains available for staging, demonstration, and experimentation.

---

# Hopsworks to Azure Blob Migration

The first MLOps implementation used Hopsworks for both the feature store and model registry.

That implementation was retained, but the production architecture was later migrated to Azure Blob Storage so the deployed system would not depend on Hopsworks service availability or free-tier compute limits.

The migration introduced backend-neutral repository interfaces and Azure Blob implementations for:

- feature datasets;
- model versions;
- registry indexes;
- production model pointers;
- immutable model artifacts.

The production model registry now follows a structure similar to:

```text
model-registry/
└── pearls_aqi_pm25_forecaster/
    ├── index.json
    ├── production/
    │   └── pointer.json
    └── versions/
        └── 1/
            ├── best_model.joblib
            ├── manifest.json
            ├── model_feature_columns.json
            ├── model_metadata.json
            ├── model_selection_report.json
            └── registry_metadata.json
```

The migration was validated independently across:

- feature synchronization;
- feature freshness;
- 72-hour forecast generation;
- AQI publication;
- production API serving;
- daily retraining;
- safe champion/challenger behavior;
- production monitoring;
- scheduled Azure executions.

The final production jobs contain **no Hopsworks environment variables or Hopsworks secrets**.

This migration intentionally did not remove Hopsworks from the codebase. It changed Hopsworks from a production dependency into an optional backend.

---

# Artifact Publication

Forecast artifacts are not published directly into a mutable serving directory.

Each valid execution creates an immutable package:

```text
aqi/runs/<run-id>/
├── alert_episodes.json
├── aqi_forecast_summary.json
├── aqi_metadata.json
├── live_pm25_aqi_forecast.parquet
├── manifest.json
└── phase_6_validation_report.json
```

The manifest records artifact information including:

- file names;
- sizes;
- content types;
- SHA-256 checksums.

After the complete package passes validation, production serving state advances through:

```text
aqi/latest/pointer.json
```

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

A failed or incomplete execution therefore cannot replace the previous valid forecast.

---

# Production Monitoring

Production-health snapshots are stored under:

```text
production-health/runs/<run-id>/
```

The latest state is referenced through:

```text
production-health/latest/pointer.json
```

Notification state is persisted under:

```text
production-health/notifications/
├── outbox.json
└── receipts/
```

This provides:

- durable incident state;
- incident deduplication;
- pending-delivery persistence;
- delivery receipts;
- incident-change tracking.

External notifications are delivered through **Azure Communication Services Email** using the production managed identity.

The notification flow is:

```text
Production health check
        │
        ▼
Incident evaluation
        │
        ▼
Durable outbox
        │
        ▼
ACS Email
        │
        ▼
Delivery receipt
```

Monitoring and forecast serving remain independent: notification failure cannot invalidate an otherwise valid forecast publication.

---

# Production Release Model

Production Docker images use immutable release tags rather than a mutable `latest` tag.

```text
walpole.azurecr.io/pearls-aqi/api:<git-sha>
walpole.azurecr.io/pearls-aqi/dashboard:<git-sha>
walpole.azurecr.io/pearls-aqi/pipeline:<git-sha>
```

Images contain OCI metadata such as:

- image title;
- application version;
- Git revision;
- build timestamp.

Runtime containers use non-root users.

The original production application release used:

```text
0d5380b79b54c1c333ce1fec4ebfbfe01bef8cc7
```

The production pipeline was later rebuilt for the Hopsworks-independent backend migration using:

```text
030d2e51cc5afffe1afa90467d9e69a7ae73ab49
```

Production deployment scripts require an explicit immutable image tag. They do not automatically assume that the current Git `HEAD` has a corresponding image in Azure Container Registry.

---

# Production Evidence

Curated machine-readable validation reports are stored under:

```text
reports/phase_10/
```

They document areas such as:

- production infrastructure;
- immutable image validation;
- scheduled-job validation;
- initial publication;
- API deployment;
- dashboard deployment;
- forecast publication;
- feature synchronization;
- retraining;
- monitoring;
- artifact repository behavior;
- model registry publication.

These reports are validation evidence rather than application runtime requirements.

Secret values are not intentionally included.

---

# Repository Structure

```text
pearls-aqi-predictor/
├── app/
│   ├── api/                    # FastAPI service
│   ├── core/                   # Shared configuration
│   ├── data_sources/           # PM2.5 and weather clients
│   ├── inference/              # Model loading and inference
│   ├── mlops/                  # Feature/model repository abstractions
│   ├── notifications/          # External notification integrations
│   ├── operations/             # Monitoring and validation
│   ├── pipelines/              # Production workflows
│   └── storage/                # Local and Azure Blob repositories
│
├── dashboard/                  # Streamlit application
├── notebooks/                  # Phase-by-phase development notebooks
├── models/                     # Local/fallback model artifacts
├── aqi/                        # Local AQI artifacts
├── inference/                  # Local inference artifacts
│
├── reports/
│   └── phase_10/               # Curated deployment evidence
│
├── scripts/                    # Deployment and validation scripts
├── tests/                      # Automated tests
├── config/                     # Configuration contracts
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

- Python
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

- backend-neutral feature repository
- Azure Blob Feature Store
- backend-neutral model registry
- Azure Blob Model Registry
- Hopsworks Feature Store
- Hopsworks Model Registry
- immutable artifact publication
- automated retraining evaluation
- champion/challenger comparison

## Infrastructure

- Docker
- Docker Compose
- Azure Container Registry
- Azure Container Apps
- Azure Container Apps Jobs
- Azure Blob Storage
- Azure Managed Identity
- Azure Communication Services Email
- Azure Resource Manager
- Azure CLI
- Git / GitHub
- `uv`

---

# Getting Started

## Prerequisites

Install:

- Python
- Git
- `uv`
- Docker
- Docker Compose
- Azure CLI for Azure operations

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

## Install Dependencies

```bash
uv sync --all-groups
source .venv/bin/activate
```

Commands can also be executed directly through `uv`:

```bash
uv run python --version
```

---

# Environment Configuration

Example environment files are provided:

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

Never commit real:

- API keys;
- Hopsworks credentials;
- email recipients;
- ACS credentials;
- Azure storage keys;
- SAS tokens;
- bearer tokens.

Azure-hosted production workloads use managed identity where supported.

### Local pipeline

```env
OPENAQ_API_KEY=replace-with-your-key

MODEL_LOADING_MODE=LOCAL_ARTIFACT
ARTIFACT_BACKEND=local
```

### Azure Blob-backed pipeline

```env
FEATURE_STORE_BACKEND=azure_blob
MODEL_REGISTRY_BACKEND=azure_blob
MODEL_LOADING_MODE=AZURE_BLOB_REGISTRY

ARTIFACT_BACKEND=azure_blob

AZURE_STORAGE_ACCOUNT=replace-with-storage-account
AZURE_STORAGE_CONTAINER=artifacts-prod
AZURE_FEATURE_STORE_PREFIX=feature-store
AZURE_MODEL_REGISTRY_PREFIX=model-registry
```

### Optional Hopsworks backend

```env
FEATURE_STORE_BACKEND=hopsworks
MODEL_REGISTRY_BACKEND=hopsworks

HOPSWORKS_API_KEY=replace-with-key
HOPSWORKS_PROJECT=replace-with-project
HOPSWORKS_HOST=replace-with-host
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

Useful endpoints:

```text
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

Configure the API:

```env
FASTAPI_BASE_URL=http://localhost:8000/api/v1
```

---

## Production-style Pipelines

Hourly feature synchronization:

```bash
uv run python -m app.pipelines.hourly_features
```

Forecast publication:

```bash
uv run python -m app.pipelines.publish_forecast
```

Daily retraining:

```bash
uv run python -m app.pipelines.daily_retraining
```

Production-health inspection:

```bash
uv run python -m app.operations.persist_production_health
```

---

# Docker Workflow

Use a full immutable Git SHA when producing release images:

```bash
export IMAGE_TAG="$(git rev-parse HEAD)"
```

Build API:

```bash
docker build \
  -f Dockerfile.api \
  -t "pearls-aqi-api:${IMAGE_TAG}" \
  .
```

Build dashboard:

```bash
docker build \
  -f Dockerfile.dashboard \
  -t "pearls-aqi-dashboard:${IMAGE_TAG}" \
  .
```

Build pipeline:

```bash
docker build \
  -f Dockerfile.pipeline \
  -t "pearls-aqi-pipeline:${IMAGE_TAG}" \
  .
```

Run API and dashboard locally:

```bash
docker compose \
  -f compose.production.yml \
  up -d api dashboard
```

Stop:

```bash
docker compose \
  -f compose.production.yml \
  down
```

---

# Testing

Run the complete suite:

```bash
uv run pytest -v
```

API tests:

```bash
uv run pytest tests/api -v
```

Dashboard tests:

```bash
uv run pytest tests/dashboard -v
```

---

# Azure Deployment

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

They run inside the shared:

```text
cae-pearls-aqi-staging
```

Container Apps Environment because of the subscription environment quota.

Production deployment scripts use explicit immutable image tags.

Example:

```bash
export PIPELINE_IMAGE_TAG="<existing-acr-image-sha>"
```

Production scheduled workloads can then be deployed through:

```bash
./scripts/deploy_production_jobs.sh
```

The production script:

- creates missing jobs;
- updates existing jobs in place;
- restores schedules explicitly;
- configures Azure Blob feature/model backends;
- removes legacy production Hopsworks configuration;
- configures ACS email monitoring;
- validates the resulting job state.

---

# Security and Reliability

## Managed Identity

Azure-hosted workloads use a user-assigned managed identity.

Required roles depend on workload, including:

```text
AcrPull
Storage Blob Data Contributor
Reader
Communication and Email Service access
```

Registry passwords and Blob storage keys are not embedded in production images.

## Secret References

Production Container Apps secrets are limited to values that genuinely require secret handling.

Examples include:

```text
OPENAQ_API_KEY
production-health-email-recipient
```

Hopsworks credentials are not present in the final production jobs.

## Non-root containers

```text
API        → pearls
Dashboard  → dashboard
Pipeline   → pipeline
```

## Forecast Freshness

```text
0 – 7 hours      FRESH
7 – 13 hours     AGING
> 13 hours       STALE
```

These thresholds align with the six-hour forecast publication schedule while allowing execution tolerance.

## Failure and Recovery

The system is designed so that:

- failed forecast runs do not replace valid artifacts;
- the latest pointer remains unchanged after failed publication;
- the API continues serving the previous valid forecast;
- successful recovery creates a new immutable run;
- serving state advances only after validation;
- the API discovers newly published artifacts without redeployment;
- retraining cannot replace the production model merely because training completed;
- monitoring and notification failures do not corrupt forecast state.

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

- [x] air-quality and weather source validation
- [x] historical dataset creation
- [x] feature engineering
- [x] chronological model evaluation
- [x] model explainability
- [x] 72-hour PM2.5 forecasting
- [x] AQI conversion and alert generation
- [x] FastAPI service
- [x] Streamlit dashboard
- [x] Docker production images
- [x] Azure Container Registry
- [x] immutable Azure Blob artifact publication
- [x] Hopsworks feature-store implementation
- [x] Hopsworks model-registry implementation
- [x] backend-neutral feature repository
- [x] Azure Blob feature repository
- [x] backend-neutral model registry
- [x] Azure Blob model registry
- [x] automated feature synchronization
- [x] automated forecast publication
- [x] automated retraining evaluation
- [x] champion/challenger promotion safeguards
- [x] durable production-health monitoring
- [x] incident deduplication and notification outbox
- [x] Azure Communication Services email alerts
- [x] managed-identity authentication
- [x] staging deployment
- [x] production deployment
- [x] staging/production artifact isolation
- [x] immutable production releases
- [x] Hopsworks-independent production workloads
- [x] end-to-end production independence validation

## Accepted Infrastructure Constraint

**Shared Container Apps Environment**

Staging and production share one Azure Container Apps Environment because of the Azure for Students subscription quota.

Application state, identities, jobs, storage boundaries, and runtime configuration remain separated.

---

## Disclaimer

This project provides PM2.5 forecasting and indicative AQI information for educational, research, and engineering purposes.

It is not an official regulatory air-quality service and should not replace guidance issued by government or environmental authorities.
