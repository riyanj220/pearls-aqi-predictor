#!/usr/bin/env bash

set -euo pipefail

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-pearls-aqi-staging}"
ENVIRONMENT="${AZURE_CONTAINER_APP_ENVIRONMENT:-cae-pearls-aqi-staging}"

JOB_NAME="${AZURE_MONITORING_JOB_NAME:-job-pearls-aqi-monitoring}"
CRON_EXPRESSION="${AZURE_MONITORING_CRON:-45 * * * *}"

IDENTITY_NAME="${AZURE_MANAGED_IDENTITY_NAME:-id-pearls-aqi-staging}"

ACR_NAME="${AZURE_ACR_NAME:-walpole}"
ACR_SERVER="${AZURE_ACR_SERVER:-walpole.azurecr.io}"
IMAGE_REPOSITORY="${AZURE_PIPELINE_IMAGE_REPOSITORY:-pearls-aqi/pipeline}"

STORAGE_ACCOUNT="${AZURE_STORAGE_ACCOUNT:-stpearlsaqiriyan}"
STORAGE_CONTAINER="${AZURE_STORAGE_CONTAINER:-artifacts}"

IMAGE_TAG="${PIPELINE_IMAGE_TAG:-$(git rev-parse HEAD)}"
IMAGE="${ACR_SERVER}/${IMAGE_REPOSITORY}:${IMAGE_TAG}"

SUBSCRIPTION_ID="$(
  az account show \
    --query id \
    --output tsv
)"

required_variables=(
  HOPSWORKS_API_KEY
  HOPSWORKS_PROJECT
  HOPSWORKS_HOST
)

for variable_name in "${required_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "Missing required variable: ${variable_name}" >&2
    exit 1
  fi
done

IDENTITY_RESOURCE_ID="$(
  az identity show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${IDENTITY_NAME}" \
    --query id \
    --output tsv
)"

IDENTITY_CLIENT_ID="$(
  az identity show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${IDENTITY_NAME}" \
    --query clientId \
    --output tsv
)"

IDENTITY_PRINCIPAL_ID="$(
  az identity show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${IDENTITY_NAME}" \
    --query principalId \
    --output tsv
)"

RESOURCE_GROUP_ID="$(
  az group show \
    --name "${RESOURCE_GROUP}" \
    --query id \
    --output tsv
)"

ensure_role_assignment() {
  local role_name="$1"
  local scope="$2"

  local assignment_count

  assignment_count="$(
    az role assignment list \
      --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
      --scope "${scope}" \
      --role "${role_name}" \
      --query "length(@)" \
      --output tsv
  )"

  if [[ "${assignment_count}" == "0" ]]; then
    az role assignment create \
      --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
      --assignee-principal-type ServicePrincipal \
      --role "${role_name}" \
      --scope "${scope}" \
      --output none
  fi
}

# Required to read Container Apps Job execution history.
ensure_role_assignment \
  "Reader" \
  "${RESOURCE_GROUP_ID}"

if ! az acr repository show \
  --name "${ACR_NAME}" \
  --image "${IMAGE_REPOSITORY}:${IMAGE_TAG}" \
  --output none
then
  echo "Image does not exist: ${IMAGE}" >&2
  exit 1
fi

if az containerapp job show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${JOB_NAME}" \
  --output none \
  >/dev/null 2>&1
then
  az containerapp job delete \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${JOB_NAME}" \
    --yes \
    --output none
fi

az containerapp job create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${JOB_NAME}" \
  --environment "${ENVIRONMENT}" \
  --trigger-type Schedule \
  --cron-expression "${CRON_EXPRESSION}" \
  --replica-timeout 600 \
  --replica-retry-limit 1 \
  --replica-completion-count 1 \
  --parallelism 1 \
  --cpu 0.5 \
  --memory 1.0Gi \
  --image "${IMAGE}" \
  --container-name production-monitor \
  --command "/app/bin/run_production_health" \
  --mi-user-assigned "${IDENTITY_RESOURCE_ID}" \
  --registry-server "${ACR_SERVER}" \
  --registry-identity "${IDENTITY_RESOURCE_ID}" \
  --secrets \
    "hopsworks-api-key=${HOPSWORKS_API_KEY}" \
  --env-vars \
    "APP_ENV=staging" \
    "SERVICE_ROLE=monitoring" \
    "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
    "AZURE_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}" \
    "AZURE_JOB_QUERY_BACKEND=arm" \
    "FEATURE_STORE_BACKEND=hopsworks" \
    "MODEL_REGISTRY_BACKEND=hopsworks" \
    "MLOPS_DRY_RUN=false" \
    "HOPSWORKS_API_KEY=secretref:hopsworks-api-key" \
    "HOPSWORKS_PROJECT=${HOPSWORKS_PROJECT}" \
    "HOPSWORKS_HOST=${HOPSWORKS_HOST}" \
    "ARTIFACT_BACKEND=azure_blob" \
    "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}" \
    "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}" \
  --tags \
    "project=pearls-aqi" \
    "environment=staging" \
    "workload=production-monitoring" \
  --output none

echo "Production monitoring job deployed."
echo "Job: ${JOB_NAME}"
echo "Schedule: ${CRON_EXPRESSION} UTC"
echo "Image: ${IMAGE}"