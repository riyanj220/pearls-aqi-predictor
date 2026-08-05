# Pearls AQI Predictor

An end-to-end data science and MLOps project for forecasting PM2.5 concentration and Air Quality Index for the Zafar Memon DHA reference location in Karachi.

The system collects recent air-quality and weather data, generates a 72-hour PM2.5 forecast, converts predicted PM2.5 values into AQI categories, detects hazardous conditions, publishes validated artifacts, and serves the results through a FastAPI API and Streamlit dashboard.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Repository Structure](#repository-structure)
- [Technology Stack](#technology-stack)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Clone the Repository](#clone-the-repository)
  - [Install Dependencies with `uv`](#install-dependencies-with-uv)
  - [Environment Configuration](#environment-configuration)
- [Running the Project Locally](#running-the-project-locally)
  - [Run the API](#run-the-api-locally)
  - [Run the Dashboard](#run-the-streamlit-dashboard)
  - [Run the Forecast Pipeline](#run-the-forecast-pipeline-locally)
- [Docker Workflow](#docker-workflow)
  - [Build Docker Images](#build-docker-images)
  - [Run with Docker Compose](#run-with-docker-compose)
  - [Run the Pipeline with Docker Compose](#run-the-pipeline-with-docker-compose)
- [Testing](#testing)
- [Azure Deployment](#azure-deployment)
  - [Deployment Model](#azure-deployment-model)
  - [Publish Images to ACR](#publish-images-to-azure-container-registry)
  - [Deploy Staging Applications](#deploy-the-staging-applications)
  - [Deploy the Scheduled Forecast Job](#deploy-the-scheduled-forecast-job)
- [Reliability and Security](#reliability-and-security)
  - [Artifact Publication Safety](#artifact-publication-safety)
  - [Failure and Recovery Validation](#failure-and-recovery-validation)
  - [Authentication](#authentication)
- [Model Source](#model-source)
- [Development Notebooks](#development-notebooks)
- [Current Project Status](#current-project-status)
- [Useful Commands](#useful-commands)

---

## Project Overview

The Pearls AQI Predictor was developed as part of the 10Pearls Shine Data Science Internship.

The project covers the complete lifecycle of a data product:

- data-source discovery and validation;
- historical data collection and cleaning;
- exploratory data analysis;
- time-series feature engineering;
- chronological model evaluation;
- 72-hour PM2.5 forecasting;
- AQI conversion and alert generation;
- API and dashboard development;
- Docker-based containerization;
- Azure Blob artifact storage;
- Azure Container Registry image publication;
- Azure Container Apps deployment;
- scheduled forecasting jobs;
- failure and recovery validation;
- Hopsworks model and feature-store integration.

The project is currently in its final production deployment and operational-hardening stage.

---

## Key Features

### Data pipeline

- Collects PM2.5 observations from OpenAQ.
- Collects historical and forecast weather data from Open-Meteo.
- Validates timestamps, duplicates, missing values, coverage, and data alignment.
- Produces a canonical hourly dataset for model development.

### Forecasting

- Generates forecasts for the next 72 hours.
- Uses lag, rolling-window, trend, weather, wind, and cyclical time features.
- Uses persistence forecasts for shorter horizons where appropriate.
- Uses an XGBoost-based model for longer forecast horizons.
- Applies chronological train, validation, and test splits to prevent leakage.

### AQI and alerts

- Converts predicted PM2.5 values into indicative AQI values.
- Generates hourly and rolling 24-hour AQI information.
- Detects hazardous forecast periods.
- Produces validated JSON and Parquet artifacts.

### Application layer

- FastAPI service for forecast and health endpoints.
- Streamlit dashboard for forecast exploration.
- Structured logging and readiness checks.
- Configurable local or Azure Blob artifact source.

### MLOps and deployment

- Docker images for API, dashboard, and pipeline workloads.
- Azure Container Registry for immutable image publication.
- Azure Blob Storage for durable forecast artifacts.
- Azure Container Apps for API and dashboard hosting.
- Azure Container Apps Job for scheduled forecast generation.
- Hopsworks integration for model and feature-store workflows.
- Failure-recovery validation to ensure invalid runs do not replace the latest valid forecast.

---

## System Architecture

```text
OpenAQ API ───────────────┐
                          │
Open-Meteo API ───────────┤
                          ▼
                Live inference pipeline
                          │
                          ▼
                 PM2.5 predictions
                          │
                          ▼
                AQI and alert pipeline
                          │
                          ▼
              Validated forecast package
                          │
              ┌───────────┴───────────┐
              │                       │
              ▼                       ▼
       Local artifacts          Azure Blob Storage
              │                       │
              └───────────┬───────────┘
                          ▼
                    FastAPI service
                          │
                          ▼
                  Streamlit dashboard
```

In the deployed environment:

```text
Scheduled Azure Container Apps Job
                │
                ▼
        Pipeline Docker image
                │
                ▼
         Azure Blob Storage
                │
                ▼
       FastAPI Container App
                │
                ▼
     Streamlit Container App
```

---

## Repository Structure

```text
pearls-aqi-predictor/
├── app/
│   ├── api/                    # FastAPI application
│   ├── core/                   # Shared configuration and utilities
│   ├── data_sources/           # OpenAQ and weather clients
│   ├── inference/              # Model loading and prediction logic
│   ├── mlops/                  # Hopsworks and registry integration
│   ├── operations/             # Deployment and validation utilities
│   ├── pipelines/              # Live inference and AQI pipelines
│   └── storage/                # Local and Azure Blob artifact storage
│
├── dashboard/                  # Streamlit dashboard
├── notebooks/                  # Phase-by-phase development notebooks
├── models/                     # Local model artifacts
├── aqi/                        # AQI output artifacts
├── inference/                  # Inference run artifacts
├── reports/                    # Validation and operational reports
├── scripts/                    # Build, publish, deploy, and validation scripts
├── tests/                      # Automated tests
│
├── Dockerfile.api
├── Dockerfile.dashboard
├── Dockerfile.pipeline
├── compose.production.yml
├── compose.local-pipeline.yml
├── pyproject.toml
├── uv.lock
└── README.md
```

---

## Technology Stack

### Data and machine learning

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

### Application

- FastAPI
- Uvicorn
- Pydantic Settings
- Streamlit

### Infrastructure and MLOps

- Docker
- Docker Compose
- Azure Container Registry
- Azure Container Apps
- Azure Container Apps Jobs
- Azure Blob Storage
- Azure Managed Identity
- Hopsworks
- GitHub Actions
- `uv` package manager

---

<a id="getting-started"></a>

## Prerequisites

Install the following before running the project:

- Python 3.12
- Git
- `uv`
- Docker and Docker Compose
- Azure CLI, only for Azure-related operations

Confirm the tools are available:

```bash
python3 --version
uv --version
docker --version
docker compose version
```

Python should report a version in the `3.12.x` range.

---

## Clone the Repository

```bash
git clone https://github.com/riyanj220/pearls-aqi-predictor.git
cd pearls-aqi-predictor
```

---

## Install Dependencies with `uv`

Create the virtual environment and install all development dependency groups:

```bash
uv sync --all-groups
```

Activate the environment:

```bash
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

You may also run commands without manually activating the environment:

```bash
uv run python --version
```

---

## Environment Configuration

The project uses separate configuration styles for the API, dashboard, and pipeline.

Example files are included:

```text
.env.example
.env.api.example
.env.dashboard.example
.env.pipeline.example
```

Create your local environment file:

```bash
cp .env.example .env
```

### Important local variables

```env
OPENAQ_API_KEY=replace-with-your-openaq-key

MODEL_LOADING_MODE=LOCAL_ARTIFACT
FEATURE_STORE_BACKEND=local
MODEL_REGISTRY_BACKEND=local

ARTIFACT_BACKEND=local
```

### API artifact-source configuration

For local artifacts:

```env
PEARLS_API_ARTIFACT_BACKEND=local
PEARLS_API_ARTIFACT_TYPE=aqi
PEARLS_API_PHASE_6_LATEST_DIRECTORY=aqi/latest
```

For Azure Blob artifacts:

```env
PEARLS_API_ARTIFACT_BACKEND=azure_blob
PEARLS_API_ARTIFACT_TYPE=aqi
PEARLS_API_AZURE_STORAGE_ACCOUNT=replace-with-storage-account
PEARLS_API_AZURE_STORAGE_CONTAINER=artifacts
PEARLS_API_PHASE_6_BLOB_CACHE_DIRECTORY=.cache/api/aqi/latest
```

When `azure_blob` is selected, the API downloads the latest validated forecast package into a writable cache directory before serving it.

---

<a id="running-the-project-locally"></a>

## Run the API Locally

Start the FastAPI application with Uvicorn:

```bash
uv run uvicorn app.api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

Open:

```text
API:        http://localhost:8000
API docs:   http://localhost:8000/docs
ReDoc:      http://localhost:8000/redoc
```

Check API liveness:

```bash
curl http://localhost:8000/api/v1/health/live
```

Check readiness:

```bash
curl http://localhost:8000/api/v1/health/ready
```

Get the current forecast:

```bash
curl http://localhost:8000/api/v1/forecast
```

---

## Run the Streamlit Dashboard

Start the API first, then open another terminal and run:

```bash
uv run streamlit run dashboard/app.py \
  --server.address 0.0.0.0 \
  --server.port 8501
```

Open:

```text
http://localhost:8501
```

The dashboard expects the API at:

```text
http://localhost:8000/api/v1
```

This can be overridden through:

```env
FASTAPI_BASE_URL=http://localhost:8000/api/v1
```

---

## Run the Forecast Pipeline Locally

The local pipeline performs two main stages:

1. generate the 72-hour PM2.5 forecast;
2. convert the forecast to AQI and create alert artifacts.

Run live inference:

```bash
uv run python -m app.pipelines.live_inference
```

Run the AQI and alert pipeline:

```bash
uv run python -m app.pipelines.aqi_alert_pipeline
```

Run the complete forecast publication workflow:

```bash
uv run python -m app.pipelines.publish_forecast
```

The pipeline creates outputs under directories such as:

```text
inference/runs/
aqi/runs/
aqi/latest/
reports/phase_10/
```

---

## Generated Forecast Artifacts

A successful AQI pipeline run produces files similar to:

```text
aqi/latest/
├── alert_episodes.json
├── aqi_forecast_summary.json
├── aqi_metadata.json
├── live_pm25_aqi_forecast.parquet
└── phase_6_validation_report.json
```

Durable Azure runs also contain:

```text
aqi/runs/<run-id>/
├── alert_episodes.json
├── aqi_forecast_summary.json
├── aqi_metadata.json
├── live_pm25_aqi_forecast.parquet
├── manifest.json
└── phase_6_validation_report.json
```

The latest valid run is referenced through:

```text
aqi/latest/pointer.json
```

The pointer is updated only after the complete forecast package passes validation.

---

<a id="docker-workflow"></a>

## Docker Images

The project contains three production images.

### API image

```text
Dockerfile.api
```

Contains:

- FastAPI runtime;
- Azure Blob dependencies;
- local fallback forecast artifacts;
- writable Blob materialization cache;
- non-root runtime user.

### Dashboard image

```text
Dockerfile.dashboard
```

Contains:

- Streamlit;
- Plotly;
- dashboard application code;
- non-root runtime user.

### Pipeline image

```text
Dockerfile.pipeline
```

Contains:

- inference dependencies;
- XGBoost and `libgomp1`;
- Hopsworks dependencies;
- Azure Blob dependencies;
- local fallback model artifacts;
- forecast publication pipeline.

---

## Build Docker Images

Generate a Git-based image tag:

```bash
export IMAGE_TAG="$(git rev-parse --short HEAD)"
```

Build the API image:

```bash
docker build \
  --file Dockerfile.api \
  --tag "pearls-aqi-api:${IMAGE_TAG}" \
  .
```

Build the dashboard image:

```bash
docker build \
  --file Dockerfile.dashboard \
  --tag "pearls-aqi-dashboard:${IMAGE_TAG}" \
  .
```

Build the pipeline image:

```bash
docker build \
  --file Dockerfile.pipeline \
  --tag "pearls-aqi-pipeline:${IMAGE_TAG}" \
  .
```

The Git SHA tag connects an image to the exact source-code commit used to build it.

---

## Run with Docker Compose

Start the API and dashboard:

```bash
export IMAGE_TAG="$(git rev-parse --short HEAD)"

docker compose \
  --file compose.production.yml \
  up \
  --detach \
  api \
  dashboard
```

Check running services:

```bash
docker compose \
  --file compose.production.yml \
  ps
```

View logs:

```bash
docker compose \
  --file compose.production.yml \
  logs --follow api
```

```bash
docker compose \
  --file compose.production.yml \
  logs --follow dashboard
```

Stop the containers without deleting them:

```bash
docker compose \
  --file compose.production.yml \
  stop
```

Start the stopped containers again:

```bash
docker compose \
  --file compose.production.yml \
  start
```

Stop and remove the containers:

```bash
docker compose \
  --file compose.production.yml \
  down
```

Remove containers and named volumes:

```bash
docker compose \
  --file compose.production.yml \
  down --volumes
```

Use `down --volumes` carefully because it deletes data stored inside Compose-managed volumes.

---

## Run the Pipeline with Docker Compose

The pipeline is placed behind the `jobs` profile because it is a batch workload, not a continuously running service.

Run it locally with the local pipeline override:

```bash
docker compose \
  --file compose.production.yml \
  --file compose.local-pipeline.yml \
  --profile jobs \
  run --rm pipeline
```

The local override may:

- load credentials from `.env`;
- mount writable output volumes;
- connect the pipeline output to the local API;
- preserve production Compose behavior for CI.

The `--rm` flag removes the temporary pipeline container after it finishes. It does not delete the image or named volumes.

---

## Test the Dockerized Services

Check API liveness:

```bash
curl http://localhost:8000/api/v1/health/live
```

Check readiness:

```bash
curl http://localhost:8000/api/v1/health/ready
```

Check the forecast:

```bash
curl http://localhost:8000/api/v1/forecast
```

Check Streamlit health:

```bash
curl http://localhost:8501/_stcore/health
```

---

<a id="testing"></a>

## Run Automated Tests

Run the complete test suite:

```bash
uv run pytest -v
```

Run API tests:

```bash
uv run pytest tests/api -v
```

Run dashboard tests:

```bash
uv run pytest tests/dashboard -v
```

Run a specific test:

```bash
uv run pytest tests/path/to/test_file.py -v
```

---

<a id="azure-deployment"></a>

## Azure Deployment Model

The staging deployment uses the following Azure resources:

```text
Azure Resource Group
├── User-assigned Managed Identity
├── Container Apps Environment
├── FastAPI Container App
├── Streamlit Container App
├── Scheduled Forecast Container Apps Job
└── Storage Account
    └── Blob container: artifacts
```

The Azure Container Registry may exist in a separate resource group.

### Responsibility of each resource

| Resource                   | Purpose                                                            |
| -------------------------- | ------------------------------------------------------------------ |
| Azure Container Registry   | Stores versioned Docker images                                     |
| Container Apps Environment | Shared execution environment for apps and jobs                     |
| API Container App          | Serves forecast artifacts                                          |
| Dashboard Container App    | Displays API data                                                  |
| Forecast Job               | Runs the pipeline on a schedule                                    |
| Blob Storage               | Stores durable validated forecast packages                         |
| Managed Identity           | Lets Azure workloads access ACR and Blob Storage without passwords |

---

## Publish Images to Azure Container Registry

Authenticate:

```bash
az acr login --name walpole
```

Set the image tag:

```bash
export IMAGE_TAG="$(git rev-parse HEAD)"
```

Run the image publication script:

```bash
./scripts/publish_acr_images.sh
```

Published images follow a structure similar to:

```text
walpole.azurecr.io/pearls-aqi/api:<git-sha>
walpole.azurecr.io/pearls-aqi/dashboard:<git-sha>
walpole.azurecr.io/pearls-aqi/pipeline:<git-sha>
```

Immutable Git tags make deployments traceable and reproducible.

---

## Deploy the Staging Applications

The deployment script provisions or updates the staging resources:

```bash
./scripts/deploy_staging.sh
```

The script is designed to be idempotent. Running it again should update existing resources rather than create unnecessary duplicates.

---

## Deploy the Scheduled Forecast Job

Required environment variables include:

```bash
export RESOURCE_GROUP="rg-pearls-aqi-staging"
export CONTAINER_ENVIRONMENT="cae-pearls-aqi-staging"
export IDENTITY_NAME="id-pearls-aqi-staging"

export ACR_NAME="walpole"
export ACR_LOGIN_SERVER="walpole.azurecr.io"
export ACR_RESOURCE_GROUP="walpole-agent_group"

export STORAGE_ACCOUNT="replace-with-storage-account"
export STORAGE_CONTAINER="artifacts"

export FORECAST_JOB="job-pearls-aqi-forecast"
export PIPELINE_IMAGE_TAG="replace-with-published-tag"
```

Credentials must also be available:

```bash
export OPENAQ_API_KEY="..."
export HOPSWORKS_API_KEY="..."
export HOPSWORKS_PROJECT="..."
export HOPSWORKS_HOST="..."
```

Deploy or update the job:

```bash
./scripts/deploy_forecast_job.sh
```

The schedule currently follows:

```text
0 */6 * * *
```

Azure Container Apps cron schedules use UTC. This expression runs every six hours.

---

## Start a Manual Forecast Job Execution

```bash
az containerapp job start \
  --name "$FORECAST_JOB" \
  --resource-group "$RESOURCE_GROUP"
```

List recent executions:

```bash
az containerapp job execution list \
  --name "$FORECAST_JOB" \
  --resource-group "$RESOURCE_GROUP" \
  --output table
```

View job logs:

```bash
az containerapp job logs show \
  --name "$FORECAST_JOB" \
  --resource-group "$RESOURCE_GROUP" \
  --container forecast-publisher \
  --follow
```

---

<a id="reliability-and-security"></a>

## Artifact Publication Safety

The publication workflow uses immutable run directories and a latest pointer.

```text
aqi/runs/<run-id>/...
aqi/latest/pointer.json
```

The process is:

1. generate forecast files;
2. validate the files;
3. create a manifest containing checksums;
4. upload the immutable run package;
5. validate the uploaded package;
6. update `pointer.json` only after success.

This design prevents a failed or incomplete forecast execution from replacing the last valid production forecast.

---

## Failure and Recovery Validation

The project includes a controlled failure-recovery test:

```bash
./scripts/validate_forecast_job_recovery.sh
```

The validation confirms that:

- a failed forecast execution does not update the latest pointer;
- the API continues serving the previous valid forecast;
- a later successful execution creates a new run;
- the pointer advances only after successful validation;
- the API automatically begins serving the recovered run;
- no API redeployment is required.

Validation reports are stored under:

```text
reports/phase_10/
```

---

## Authentication

### Local Azure CLI authentication

Local Azure SDK commands use:

```python
DefaultAzureCredential()
```

After running:

```bash
az login
```

the Azure CLI stores a temporary authenticated session locally. `DefaultAzureCredential` can reuse this session during development.

No Azure password is stored in the project.

### Azure-hosted authentication

In Azure, the applications use a user-assigned managed identity.

The managed identity receives roles such as:

```text
AcrPull
Storage Blob Data Contributor
```

This allows the API and forecast job to access Azure resources without embedding passwords, storage keys, or registry credentials in the image.

---

## Model Source

The prediction pipeline supports multiple model-loading modes.

### Local artifact

```env
MODEL_LOADING_MODE=LOCAL_ARTIFACT
```

Loads model files from the project’s `models/` directory.

### Hopsworks registry

```env
MODEL_LOADING_MODE=HOPSWORKS_REGISTRY
```

Loads the explicitly promoted production model from Hopsworks.

Optional fallbacks:

```env
ALLOW_CACHED_REGISTRY_FALLBACK=true
ALLOW_LOCAL_MODEL_FALLBACK=true
```

The fallback strategy allows the pipeline to continue safely when the remote registry is temporarily unavailable, provided a validated cached or local model exists.

---

## Development Notebooks

The notebooks document the project phase by phase:

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

The notebooks are intended for analysis and explanation. Production execution is handled through Python modules under `app/`.

---

## Current Project Status

Completed areas include:

- data-source validation;
- canonical dataset creation;
- feature engineering;
- model training and evaluation;
- model explainability;
- live inference;
- AQI conversion and alert generation;
- FastAPI service;
- Streamlit dashboard;
- Docker images;
- Azure Container Registry publication;
- staging API and dashboard deployment;
- Azure Blob artifact publishing;
- scheduled forecast job;
- managed-identity authentication;
- failure and recovery validation.

Remaining work mainly concerns final production hardening, monitoring, operational automation, documentation refinement, and deployment cleanup.

---

## Useful Commands

### Start API locally

```bash
uv run uvicorn app.api.main:app --reload
```

### Start dashboard locally

```bash
uv run streamlit run dashboard/app.py
```

### Run complete pipeline

```bash
uv run python -m app.pipelines.publish_forecast
```

### Start Docker services

```bash
docker compose -f compose.production.yml up -d api dashboard
```

### Run Docker pipeline

```bash
docker compose \
  -f compose.production.yml \
  -f compose.local-pipeline.yml \
  --profile jobs \
  run --rm pipeline
```

### Stop Docker services

```bash
docker compose -f compose.production.yml down
```

### Run tests

```bash
uv run pytest -v
```

### Check Docker disk usage

```bash
docker system df
```

### Remove unused build cache

```bash
docker builder prune
```

Review the reclaimable space before confirming deletion.
