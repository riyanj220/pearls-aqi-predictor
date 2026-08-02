# Pearls AQI Predictor — Production Container Images

## Images

The deployment uses three independent images:

- `pearls-aqi-api`
- `pearls-aqi-dashboard`
- `pearls-aqi-pipeline`

## API image

The API image serves already validated AQI forecast artifacts.

It does not train models, fetch OpenAQ data, or write feature-store records.

It runs as a non-root user and exposes port 8000.

## Dashboard image

The dashboard image serves Streamlit and communicates with FastAPI.

It does not receive OpenAQ, Hopsworks, model-registry, or Azure Storage
credentials.

It runs as a non-root user and exposes port 8501.

## Pipeline image

The pipeline image contains the dependencies required for:

- live inference
- AQI enrichment
- feature synchronization
- retraining eligibility
- champion–challenger evaluation
- bounded backfill

It has no public ingress and no health endpoint.

Azure Container Apps Jobs will override its default command for each operation.

## Dependency isolation

Each image installs only the dependencies required for its responsibility.

The dashboard does not include XGBoost or Hopsworks.

The API does not include training dependencies.

The pipeline image is intentionally larger because it includes inference and
feature-store clients.

## Reproducibility

Dependencies are installed from the committed `uv.lock`.

The uv version is pinned.

Images receive:

- application version
- Git commit SHA
- UTC build timestamp

through OCI labels.

## Security

All images run as non-root users.

No `.env` file or secret is copied into an image.

The HTTP images include container health checks.

The pipeline image has no exposed port.

## Registry boundary

Phase 10G builds and validates images locally.

Images are pushed to the existing Azure Container Registry in Phase 10H.
