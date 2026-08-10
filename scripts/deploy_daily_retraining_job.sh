#!/usr/bin/env bash

set -euo pipefail

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-pearls-aqi-staging}"
CONTAINER_APP_ENVIRONMENT="${AZURE_CONTAINER_APP_ENVIRONMENT:-cae-pearls-aqi-staging}"

JOB_NAME="${AZURE_RETRAINING_JOB_NAME:-job-pearls-aqi-retraining}"

ACR_NAME="${AZURE_ACR_NAME:-walpole}"
ACR_SERVER="${AZURE_ACR_SERVER:-walpole.azurecr.io}"
IMAGE_REPOSITORY="${AZURE_PIPELINE_IMAGE_REPOSITORY:-pearls-aqi/pipeline}"

MANAGED_IDENTITY_NAME="${AZURE_MANAGED_IDENTITY_NAME:-id-pearls-aqi-staging}"

CRON_EXPRESSION="${AZURE_RETRAINING_CRON:-30 3 * * *}"
CPU="${AZURE_RETRAINING_CPU:-1.0}"
MEMORY="${AZURE_RETRAINING_MEMORY:-2Gi}"
TIMEOUT_SECONDS="${AZURE_RETRAINING_TIMEOUT_SECONDS:-3600}"
RETRY_LIMIT="${AZURE_RETRAINING_RETRY_LIMIT:-1}"

STORAGE_ACCOUNT="${AZURE_STORAGE_ACCOUNT:-stpearlsaqiriyan}"
STORAGE_CONTAINER="${AZURE_STORAGE_CONTAINER:-artifacts}"

IMAGE_TAG="${PIPELINE_IMAGE_TAG:-}"

if [[ -z "${IMAGE_TAG}" ]]; then
  echo "PIPELINE_IMAGE_TAG must be set to an existing ACR image tag." >&2
  exit 1
fi

IMAGE="${ACR_SERVER}/${IMAGE_REPOSITORY}:${IMAGE_TAG}"

required_environment_variables=(
  HOPSWORKS_API_KEY
  HOPSWORKS_PROJECT
  HOPSWORKS_HOST
)

for variable_name in "${required_environment_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "Missing required environment variable: ${variable_name}" >&2
    exit 1
  fi
done

echo "Resource group: ${RESOURCE_GROUP}"
echo "Container Apps environment: ${CONTAINER_APP_ENVIRONMENT}"
echo "Job name: ${JOB_NAME}"
echo "Image: ${IMAGE}"
echo "Schedule: ${CRON_EXPRESSION} UTC"

IDENTITY_RESOURCE_ID="$(
  az identity show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${MANAGED_IDENTITY_NAME}" \
    --query id \
    --output tsv
)"

if [[ -z "${IDENTITY_RESOURCE_ID}" ]]; then
  echo "Could not resolve managed identity." >&2
  exit 1
fi

if ! az acr repository show \
  --name "${ACR_NAME}" \
  --image "${IMAGE_REPOSITORY}:${IMAGE_TAG}" \
  --output none \
  >/dev/null 2>&1
then
  echo "Pipeline image does not exist in ACR: ${IMAGE}" >&2
  exit 1
fi

if az containerapp job show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${JOB_NAME}" \
  --output none \
  >/dev/null 2>&1
then
  echo "Deleting existing job before immutable redeployment."

  az containerapp job delete \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${JOB_NAME}" \
    --yes \
    --output none
fi

echo "Creating scheduled daily retraining job."

az containerapp job create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${JOB_NAME}" \
  --environment "${CONTAINER_APP_ENVIRONMENT}" \
  --trigger-type Schedule \
  --cron-expression "${CRON_EXPRESSION}" \
  --replica-timeout "${TIMEOUT_SECONDS}" \
  --replica-retry-limit "${RETRY_LIMIT}" \
  --replica-completion-count 1 \
  --parallelism 1 \
  --image "${IMAGE}" \
  --cpu "${CPU}" \
  --memory "${MEMORY}" \
  --command "/app/bin/run_daily_retraining" \
  --mi-user-assigned "${IDENTITY_RESOURCE_ID}" \
  --registry-server "${ACR_SERVER}" \
  --registry-identity "${IDENTITY_RESOURCE_ID}" \
  --secrets \
    "hopsworks-api-key=${HOPSWORKS_API_KEY}" \
  --env-vars \
    "APP_ENV=staging" \
    "SERVICE_ROLE=pipeline" \
    "FEATURE_STORE_BACKEND=hopsworks" \
    "MODEL_REGISTRY_BACKEND=hopsworks" \
    "MLOPS_DRY_RUN=false" \
    "HOPSWORKS_API_KEY=secretref:hopsworks-api-key" \
    "HOPSWORKS_PROJECT=${HOPSWORKS_PROJECT}" \
    "HOPSWORKS_HOST=${HOPSWORKS_HOST}" \
    "RUNTIME_TRAINING_OUTPUT_DIR=/app/data/training/runtime" \
    "ARTIFACT_BACKEND=azure_blob" \
    "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}" \
    "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}" \
  --output none

echo "Confirming managed identity assignment."

az containerapp job identity show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${JOB_NAME}" \
  --output json \
  >/dev/null

echo "Daily retraining job deployed successfully."