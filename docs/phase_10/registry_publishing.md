# Pearls AQI Predictor — Registry Publishing

## Registry

The project reuses the existing Azure Container Registry:

```text
walpole.azurecr.io

The existing Walpole repositories are not modified.

Pearls AQI images use an isolated namespace:

pearls-aqi/api
pearls-aqi/dashboard
pearls-aqi/pipeline


## Image tags

Every image is tagged with the complete Git commit SHA.

Example:

walpole.azurecr.io/pearls-aqi/api/<git-sha>

A full Git SHA provides direct traceability between:

source code
container image
deployment revision
operational report
rollback target

The latest tag is not used.


## Authentication

Local manual publication uses:

az login
az acr login --name walpole

No registry password or administrator account is required.
Future Container Apps workloads will pull images through managed identity.


## Published images

The registry stores:

FastAPI serving image
Streamlit dashboard image
batch pipeline image

Each image was locally validated before publication.


## Deployment boundary

Phase 10H publishes and verifies images only.
It does not deploy Container Apps or Container Apps Jobs.
Staging deployment begins in Phase 10I.
```
