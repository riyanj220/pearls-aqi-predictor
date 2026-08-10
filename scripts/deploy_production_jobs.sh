#!/usr/bin/env bash

set -Eeuo pipefail

# -----------------------------------------------------------------------------
# Production scheduled jobs deployment
# -----------------------------------------------------------------------------
#
# Deploys or updates the four production Container Apps Jobs without requiring
# Hopsworks:
#
#   - hourly feature synchronization
#   - 6-hour forecast publication
#   - daily retraining
#   - hourly production monitoring + ACS email notification
#
# Production reuses the shared Container Apps Environment in the staging
# resource group because the Azure for Students subscription has a single
# Container Apps Environment quota.
#
# This script is intentionally idempotent:
#   - missing jobs are created
#   - existing jobs are updated in place
#   - schedules are explicitly patched after update
#   - legacy Hopsworks/webhook configuration is removed
#
# IMPORTANT:
# PIPELINE_IMAGE_TAG (or RELEASE_SHA) must point to an image that already exists
# in ACR. The script does not default to the current Git HEAD because script-only
# commits do not necessarily have a matching container image.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

PRODUCTION_RESOURCE_GROUP="${PRODUCTION_RESOURCE_GROUP:-rg-pearls-aqi-prod}"

ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-cae-pearls-aqi-staging}"
ENVIRONMENT_RESOURCE_GROUP="${ENVIRONMENT_RESOURCE_GROUP:-rg-pearls-aqi-staging}"

IDENTITY_NAME="${IDENTITY_NAME:-id-pearls-aqi-prod}"

ACR_NAME="${ACR_NAME:-walpole}"
ACR_SERVER="${ACR_SERVER:-walpole.azurecr.io}"
PIPELINE_IMAGE_REPOSITORY="${PIPELINE_IMAGE_REPOSITORY:-pearls-aqi/pipeline}"

STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-stpearlsaqiriyan}"
STORAGE_RESOURCE_GROUP="${STORAGE_RESOURCE_GROUP:-rg-pearls-aqi-staging}"
STORAGE_CONTAINER="${STORAGE_CONTAINER:-artifacts-prod}"

FEATURE_STORE_PREFIX="${FEATURE_STORE_PREFIX:-feature-store}"
MODEL_REGISTRY_PREFIX="${MODEL_REGISTRY_PREFIX:-model-registry}"

FEATURE_JOB="${FEATURE_JOB:-job-pearls-aqi-features-prod}"
FORECAST_JOB="${FORECAST_JOB:-job-pearls-aqi-forecast-prod}"
RETRAINING_JOB="${RETRAINING_JOB:-job-pearls-aqi-retraining-prod}"
MONITORING_JOB="${MONITORING_JOB:-job-pearls-aqi-monitoring-prod}"

FEATURE_CRON="${FEATURE_CRON:-15 * * * *}"
FORECAST_CRON="${FORECAST_CRON:-0 */6 * * *}"
RETRAINING_CRON="${RETRAINING_CRON:-30 3 * * *}"
MONITORING_CRON="${MONITORING_CRON:-45 * * * *}"

FEATURE_CPU="${FEATURE_CPU:-0.5}"
FEATURE_MEMORY="${FEATURE_MEMORY:-1.0Gi}"
FEATURE_TIMEOUT="${FEATURE_TIMEOUT:-2700}"

FORECAST_CPU="${FORECAST_CPU:-0.5}"
FORECAST_MEMORY="${FORECAST_MEMORY:-1.0Gi}"
FORECAST_TIMEOUT="${FORECAST_TIMEOUT:-1800}"

RETRAINING_CPU="${RETRAINING_CPU:-1.0}"
RETRAINING_MEMORY="${RETRAINING_MEMORY:-2.0Gi}"
RETRAINING_TIMEOUT="${RETRAINING_TIMEOUT:-3600}"

MONITORING_CPU="${MONITORING_CPU:-0.5}"
MONITORING_MEMORY="${MONITORING_MEMORY:-1.0Gi}"
MONITORING_TIMEOUT="${MONITORING_TIMEOUT:-600}"

REPLICA_RETRY_LIMIT="${REPLICA_RETRY_LIMIT:-1}"

IMAGE_TAG="${PIPELINE_IMAGE_TAG:-${RELEASE_SHA:-}}"

if [[ -z "${IMAGE_TAG}" ]]; then
  echo \
    "PIPELINE_IMAGE_TAG or RELEASE_SHA must be set to an immutable ACR image tag." \
    >&2
  exit 1
fi

PIPELINE_IMAGE="${ACR_SERVER}/${PIPELINE_IMAGE_REPOSITORY}:${IMAGE_TAG}"

# -----------------------------------------------------------------------------
# Required runtime values
# -----------------------------------------------------------------------------

required_variables=(
  OPENAQ_API_KEY
  PRODUCTION_HEALTH_EMAIL_ENDPOINT
  PRODUCTION_HEALTH_EMAIL_SENDER
  PRODUCTION_HEALTH_EMAIL_RECIPIENT
)

for variable_name in "${required_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "Missing required environment variable: ${variable_name}" >&2
    exit 1
  fi
done

# -----------------------------------------------------------------------------
# Azure helpers
# -----------------------------------------------------------------------------

job_exists() {
  local job_name="$1"

  az containerapp job show \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${job_name}" \
    --output none \
    >/dev/null 2>&1
}

ensure_role_assignment() {
  local role_name="$1"
  local scope="$2"

  local assignment_count

  assignment_count="$(
    az role assignment list \
      --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
      --scope "${scope}" \
      --role "${role_name}" \
      --query 'length(@)' \
      --output tsv
  )"

  if [[ "${assignment_count}" == "0" ]]; then
    echo "Assigning ${role_name} at ${scope}"

    az role assignment create \
      --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
      --assignee-principal-type ServicePrincipal \
      --role "${role_name}" \
      --scope "${scope}" \
      --output none
  else
    echo "${role_name} already assigned."
  fi
}

patch_schedule() {
  local job_name="$1"
  local cron_expression="$2"
  local timeout_seconds="$3"

  az rest \
    --method PATCH \
    --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${PRODUCTION_RESOURCE_GROUP}/providers/Microsoft.App/jobs/${job_name}?api-version=2025-07-01" \
    --headers "Content-Type=application/json" \
    --body "{
      \"properties\": {
        \"configuration\": {
          \"triggerType\": \"Schedule\",
          \"replicaTimeout\": ${timeout_seconds},
          \"replicaRetryLimit\": ${REPLICA_RETRY_LIMIT},
          \"scheduleTriggerConfig\": {
            \"cronExpression\": \"${cron_expression}\",
            \"parallelism\": 1,
            \"replicaCompletionCount\": 1
          }
        }
      }
    }" \
    --output none
}

remove_legacy_env_vars() {
  local job_name="$1"
  shift

  if (( $# == 0 )); then
    return 0
  fi

  az containerapp job update \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${job_name}" \
    --remove-env-vars "$@" \
    --output none \
    2>/dev/null || true
}

remove_legacy_secrets() {
  local job_name="$1"
  shift

  if (( $# == 0 )); then
    return 0
  fi

  az containerapp job secret remove \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${job_name}" \
    --secret-names "$@" \
    --output none \
    2>/dev/null || true
}

verify_job() {
  local job_name="$1"

  az containerapp job show \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${job_name}" \
    --query '{
      name:name,
      provisioningState:properties.provisioningState,
      triggerType:properties.configuration.triggerType,
      cron:properties.configuration.scheduleTriggerConfig.cronExpression,
      image:properties.template.containers[0].image,
      command:properties.template.containers[0].command
    }' \
    --output json
}

# -----------------------------------------------------------------------------
# Preflight
# -----------------------------------------------------------------------------

echo "Validating production job deployment prerequisites..."

az account show --output none

SUBSCRIPTION_ID="$(
  az account show \
    --query id \
    --output tsv
)"

ENVIRONMENT_RESOURCE_ID="$(
  az containerapp env show \
    --resource-group "${ENVIRONMENT_RESOURCE_GROUP}" \
    --name "${ENVIRONMENT_NAME}" \
    --query id \
    --output tsv
)"

IDENTITY_RESOURCE_ID="$(
  az identity show \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${IDENTITY_NAME}" \
    --query id \
    --output tsv
)"

IDENTITY_CLIENT_ID="$(
  az identity show \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${IDENTITY_NAME}" \
    --query clientId \
    --output tsv
)"

IDENTITY_PRINCIPAL_ID="$(
  az identity show \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${IDENTITY_NAME}" \
    --query principalId \
    --output tsv
)"

ACR_RESOURCE_ID="$(
  az acr show \
    --name "${ACR_NAME}" \
    --query id \
    --output tsv
)"

STORAGE_RESOURCE_ID="$(
  az storage account show \
    --resource-group "${STORAGE_RESOURCE_GROUP}" \
    --name "${STORAGE_ACCOUNT}" \
    --query id \
    --output tsv
)"

PRODUCTION_RESOURCE_GROUP_ID="$(
  az group show \
    --name "${PRODUCTION_RESOURCE_GROUP}" \
    --query id \
    --output tsv
)"

if ! az acr repository show \
  --name "${ACR_NAME}" \
  --image "${PIPELINE_IMAGE_REPOSITORY}:${IMAGE_TAG}" \
  --output none \
  >/dev/null 2>&1
then
  echo "Pipeline image does not exist in ACR: ${PIPELINE_IMAGE}" >&2
  exit 1
fi

echo "Using immutable image: ${PIPELINE_IMAGE}"
echo "Using shared Container Apps Environment: ${ENVIRONMENT_RESOURCE_ID}"

# The production identity pulls the private image.
ensure_role_assignment \
  "AcrPull" \
  "${ACR_RESOURCE_ID}"

# Production workloads read/write durable Blob data.
ensure_role_assignment \
  "Storage Blob Data Contributor" \
  "${STORAGE_RESOURCE_ID}"

# Monitoring inspects production Container Apps Jobs through ARM.
ensure_role_assignment \
  "Reader" \
  "${PRODUCTION_RESOURCE_GROUP_ID}"

# Azure Communication Services email RBAC is expected to be provisioned by
# production infrastructure setup. This script configures the monitoring job
# to use that already-authorized managed identity.

# -----------------------------------------------------------------------------
# 1. Hourly feature job
# -----------------------------------------------------------------------------

echo
echo "Deploying production feature job: ${FEATURE_JOB}"

FEATURE_ENV_VARS=(
  "APP_ENV=production"
  "SERVICE_ROLE=hourly_features"

  "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}"

  "FEATURE_STORE_BACKEND=azure_blob"
  "MLOPS_DRY_RUN=false"

  "OPENAQ_API_KEY=secretref:openaq-api-key"

  "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}"
  "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}"
  "AZURE_FEATURE_STORE_PREFIX=${FEATURE_STORE_PREFIX}"
)

if job_exists "${FEATURE_JOB}"; then
  az containerapp job identity assign \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${FEATURE_JOB}" \
    --user-assigned "${IDENTITY_RESOURCE_ID}" \
    --output none

  az containerapp job secret set \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${FEATURE_JOB}" \
    --secrets \
      "openaq-api-key=${OPENAQ_API_KEY}" \
    --output none

  az containerapp job update \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${FEATURE_JOB}" \
    --image "${PIPELINE_IMAGE}" \
    --container-name hourly-features \
    --cpu "${FEATURE_CPU}" \
    --memory "${FEATURE_MEMORY}" \
    --command "/app/bin/run_hourly_features" \
    --set-env-vars "${FEATURE_ENV_VARS[@]}" \
    --tags \
      "project=pearls-aqi" \
      "environment=production" \
      "workload=hourly-features" \
      "release=${IMAGE_TAG}" \
    --output none
else
  az containerapp job create \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${FEATURE_JOB}" \
    --environment "${ENVIRONMENT_RESOURCE_ID}" \
    --trigger-type Schedule \
    --cron-expression "${FEATURE_CRON}" \
    --replica-timeout "${FEATURE_TIMEOUT}" \
    --replica-retry-limit "${REPLICA_RETRY_LIMIT}" \
    --replica-completion-count 1 \
    --parallelism 1 \
    --cpu "${FEATURE_CPU}" \
    --memory "${FEATURE_MEMORY}" \
    --image "${PIPELINE_IMAGE}" \
    --container-name hourly-features \
    --command "/app/bin/run_hourly_features" \
    --mi-user-assigned "${IDENTITY_RESOURCE_ID}" \
    --registry-server "${ACR_SERVER}" \
    --registry-identity "${IDENTITY_RESOURCE_ID}" \
    --secrets \
      "openaq-api-key=${OPENAQ_API_KEY}" \
    --env-vars "${FEATURE_ENV_VARS[@]}" \
    --tags \
      "project=pearls-aqi" \
      "environment=production" \
      "workload=hourly-features" \
      "release=${IMAGE_TAG}" \
    --output none
fi

az containerapp job registry set \
  --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
  --name "${FEATURE_JOB}" \
  --server "${ACR_SERVER}" \
  --identity "${IDENTITY_RESOURCE_ID}" \
  --output none

remove_legacy_env_vars \
  "${FEATURE_JOB}" \
  HOPSWORKS_API_KEY \
  HOPSWORKS_PROJECT \
  HOPSWORKS_HOST \
  HOPSWORKS_PORT \
  HOPSWORKS_ENGINE \
  HOPSWORKS_HOSTNAME_VERIFICATION \
  MODEL_REGISTRY_BACKEND

remove_legacy_secrets \
  "${FEATURE_JOB}" \
  hopsworks-api-key

patch_schedule \
  "${FEATURE_JOB}" \
  "${FEATURE_CRON}" \
  "${FEATURE_TIMEOUT}"

# -----------------------------------------------------------------------------
# 2. Forecast publication job
# -----------------------------------------------------------------------------

echo
echo "Deploying production forecast job: ${FORECAST_JOB}"

FORECAST_ENV_VARS=(
  "APP_ENV=production"
  "SERVICE_ROLE=forecast"

  "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}"

  "ARTIFACT_BACKEND=azure_blob"

  "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}"
  "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}"

  "FEATURE_STORE_BACKEND=azure_blob"
  "MODEL_REGISTRY_BACKEND=azure_blob"
  "MODEL_LOADING_MODE=AZURE_BLOB_REGISTRY"

  "AZURE_FEATURE_STORE_PREFIX=${FEATURE_STORE_PREFIX}"
  "AZURE_MODEL_REGISTRY_PREFIX=${MODEL_REGISTRY_PREFIX}"

  "MLOPS_DRY_RUN=false"

  "OPENAQ_API_KEY=secretref:openaq-api-key"
)

if job_exists "${FORECAST_JOB}"; then
  az containerapp job identity assign \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${FORECAST_JOB}" \
    --user-assigned "${IDENTITY_RESOURCE_ID}" \
    --output none

  az containerapp job secret set \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${FORECAST_JOB}" \
    --secrets \
      "openaq-api-key=${OPENAQ_API_KEY}" \
    --output none

  az containerapp job update \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${FORECAST_JOB}" \
    --image "${PIPELINE_IMAGE}" \
    --container-name forecast-publication \
    --cpu "${FORECAST_CPU}" \
    --memory "${FORECAST_MEMORY}" \
    --set-env-vars "${FORECAST_ENV_VARS[@]}" \
    --tags \
      "project=pearls-aqi" \
      "environment=production" \
      "workload=forecast-publication" \
      "release=${IMAGE_TAG}" \
    --output none
else
  az containerapp job create \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${FORECAST_JOB}" \
    --environment "${ENVIRONMENT_RESOURCE_ID}" \
    --trigger-type Schedule \
    --cron-expression "${FORECAST_CRON}" \
    --replica-timeout "${FORECAST_TIMEOUT}" \
    --replica-retry-limit "${REPLICA_RETRY_LIMIT}" \
    --replica-completion-count 1 \
    --parallelism 1 \
    --cpu "${FORECAST_CPU}" \
    --memory "${FORECAST_MEMORY}" \
    --image "${PIPELINE_IMAGE}" \
    --container-name forecast-publication \
    --mi-user-assigned "${IDENTITY_RESOURCE_ID}" \
    --registry-server "${ACR_SERVER}" \
    --registry-identity "${IDENTITY_RESOURCE_ID}" \
    --secrets \
      "openaq-api-key=${OPENAQ_API_KEY}" \
    --env-vars "${FORECAST_ENV_VARS[@]}" \
    --tags \
      "project=pearls-aqi" \
      "environment=production" \
      "workload=forecast-publication" \
      "release=${IMAGE_TAG}" \
    --output none
fi

az containerapp job registry set \
  --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
  --name "${FORECAST_JOB}" \
  --server "${ACR_SERVER}" \
  --identity "${IDENTITY_RESOURCE_ID}" \
  --output none

remove_legacy_env_vars \
  "${FORECAST_JOB}" \
  HOPSWORKS_API_KEY \
  HOPSWORKS_PROJECT \
  HOPSWORKS_HOST \
  HOPSWORKS_PORT \
  HOPSWORKS_ENGINE \
  HOPSWORKS_HOSTNAME_VERIFICATION \
  ALLOW_CACHED_REGISTRY_FALLBACK \
  ALLOW_LOCAL_MODEL_FALLBACK

remove_legacy_secrets \
  "${FORECAST_JOB}" \
  hopsworks-api-key

patch_schedule \
  "${FORECAST_JOB}" \
  "${FORECAST_CRON}" \
  "${FORECAST_TIMEOUT}"

# -----------------------------------------------------------------------------
# 3. Daily retraining job
# -----------------------------------------------------------------------------

echo
echo "Deploying production retraining job: ${RETRAINING_JOB}"

RETRAINING_ENV_VARS=(
  "APP_ENV=production"
  "SERVICE_ROLE=retraining"

  "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}"

  "ARTIFACT_BACKEND=azure_blob"

  "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}"
  "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}"

  "FEATURE_STORE_BACKEND=azure_blob"
  "MODEL_REGISTRY_BACKEND=azure_blob"

  "AZURE_FEATURE_STORE_PREFIX=${FEATURE_STORE_PREFIX}"
  "AZURE_MODEL_REGISTRY_PREFIX=${MODEL_REGISTRY_PREFIX}"

  "MLOPS_DRY_RUN=false"
)

if job_exists "${RETRAINING_JOB}"; then
  az containerapp job identity assign \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${RETRAINING_JOB}" \
    --user-assigned "${IDENTITY_RESOURCE_ID}" \
    --output none

  az containerapp job update \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${RETRAINING_JOB}" \
    --image "${PIPELINE_IMAGE}" \
    --container-name daily-retraining \
    --cpu "${RETRAINING_CPU}" \
    --memory "${RETRAINING_MEMORY}" \
    --command "/app/bin/run_daily_retraining" \
    --set-env-vars "${RETRAINING_ENV_VARS[@]}" \
    --tags \
      "project=pearls-aqi" \
      "environment=production" \
      "workload=daily-retraining" \
      "release=${IMAGE_TAG}" \
    --output none
else
  az containerapp job create \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${RETRAINING_JOB}" \
    --environment "${ENVIRONMENT_RESOURCE_ID}" \
    --trigger-type Schedule \
    --cron-expression "${RETRAINING_CRON}" \
    --replica-timeout "${RETRAINING_TIMEOUT}" \
    --replica-retry-limit "${REPLICA_RETRY_LIMIT}" \
    --replica-completion-count 1 \
    --parallelism 1 \
    --cpu "${RETRAINING_CPU}" \
    --memory "${RETRAINING_MEMORY}" \
    --image "${PIPELINE_IMAGE}" \
    --container-name daily-retraining \
    --command "/app/bin/run_daily_retraining" \
    --mi-user-assigned "${IDENTITY_RESOURCE_ID}" \
    --registry-server "${ACR_SERVER}" \
    --registry-identity "${IDENTITY_RESOURCE_ID}" \
    --env-vars "${RETRAINING_ENV_VARS[@]}" \
    --tags \
      "project=pearls-aqi" \
      "environment=production" \
      "workload=daily-retraining" \
      "release=${IMAGE_TAG}" \
    --output none
fi

az containerapp job registry set \
  --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
  --name "${RETRAINING_JOB}" \
  --server "${ACR_SERVER}" \
  --identity "${IDENTITY_RESOURCE_ID}" \
  --output none

remove_legacy_env_vars \
  "${RETRAINING_JOB}" \
  HOPSWORKS_API_KEY \
  HOPSWORKS_PROJECT \
  HOPSWORKS_HOST \
  HOPSWORKS_PORT \
  HOPSWORKS_ENGINE \
  HOPSWORKS_HOSTNAME_VERIFICATION

remove_legacy_secrets \
  "${RETRAINING_JOB}" \
  hopsworks-api-key

patch_schedule \
  "${RETRAINING_JOB}" \
  "${RETRAINING_CRON}" \
  "${RETRAINING_TIMEOUT}"

# -----------------------------------------------------------------------------
# 4. Production monitoring job
# -----------------------------------------------------------------------------

echo
echo "Deploying production monitoring job: ${MONITORING_JOB}"

MONITORING_ENV_VARS=(
  "APP_ENV=production"
  "SERVICE_ROLE=monitoring"

  "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}"
  "AZURE_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}"
  "AZURE_JOB_QUERY_BACKEND=arm"

  "PRODUCTION_RESOURCE_GROUP=${PRODUCTION_RESOURCE_GROUP}"

  "FEATURE_JOB_NAME=${FEATURE_JOB}"
  "FORECAST_JOB_NAME=${FORECAST_JOB}"
  "RETRAINING_JOB_NAME=${RETRAINING_JOB}"

  "FEATURE_STORE_BACKEND=azure_blob"

  "MLOPS_DRY_RUN=false"

  "ARTIFACT_BACKEND=azure_blob"
  "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}"
  "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}"
  "AZURE_FEATURE_STORE_PREFIX=${FEATURE_STORE_PREFIX}"

  "PRODUCTION_HEALTH_NOTIFICATION_CHANNEL=email"
  "PRODUCTION_HEALTH_EMAIL_ENDPOINT=${PRODUCTION_HEALTH_EMAIL_ENDPOINT}"
  "PRODUCTION_HEALTH_EMAIL_SENDER=${PRODUCTION_HEALTH_EMAIL_SENDER}"
  "PRODUCTION_HEALTH_EMAIL_RECIPIENT=secretref:production-health-email-recipient"
)

if job_exists "${MONITORING_JOB}"; then
  az containerapp job identity assign \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${MONITORING_JOB}" \
    --user-assigned "${IDENTITY_RESOURCE_ID}" \
    --output none

  az containerapp job secret set \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${MONITORING_JOB}" \
    --secrets \
      "production-health-email-recipient=${PRODUCTION_HEALTH_EMAIL_RECIPIENT}" \
    --output none

  az containerapp job update \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${MONITORING_JOB}" \
    --image "${PIPELINE_IMAGE}" \
    --container-name production-monitor \
    --cpu "${MONITORING_CPU}" \
    --memory "${MONITORING_MEMORY}" \
    --command "/app/bin/run_production_health" \
    --set-env-vars "${MONITORING_ENV_VARS[@]}" \
    --tags \
      "project=pearls-aqi" \
      "environment=production" \
      "workload=production-monitoring" \
      "release=${IMAGE_TAG}" \
    --output none
else
  az containerapp job create \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${MONITORING_JOB}" \
    --environment "${ENVIRONMENT_RESOURCE_ID}" \
    --trigger-type Schedule \
    --cron-expression "${MONITORING_CRON}" \
    --replica-timeout "${MONITORING_TIMEOUT}" \
    --replica-retry-limit "${REPLICA_RETRY_LIMIT}" \
    --replica-completion-count 1 \
    --parallelism 1 \
    --cpu "${MONITORING_CPU}" \
    --memory "${MONITORING_MEMORY}" \
    --image "${PIPELINE_IMAGE}" \
    --container-name production-monitor \
    --command "/app/bin/run_production_health" \
    --mi-user-assigned "${IDENTITY_RESOURCE_ID}" \
    --registry-server "${ACR_SERVER}" \
    --registry-identity "${IDENTITY_RESOURCE_ID}" \
    --secrets \
      "production-health-email-recipient=${PRODUCTION_HEALTH_EMAIL_RECIPIENT}" \
    --env-vars "${MONITORING_ENV_VARS[@]}" \
    --tags \
      "project=pearls-aqi" \
      "environment=production" \
      "workload=production-monitoring" \
      "release=${IMAGE_TAG}" \
    --output none
fi

az containerapp job registry set \
  --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
  --name "${MONITORING_JOB}" \
  --server "${ACR_SERVER}" \
  --identity "${IDENTITY_RESOURCE_ID}" \
  --output none

remove_legacy_env_vars \
  "${MONITORING_JOB}" \
  HOPSWORKS_API_KEY \
  HOPSWORKS_PROJECT \
  HOPSWORKS_HOST \
  HOPSWORKS_PORT \
  HOPSWORKS_ENGINE \
  HOPSWORKS_HOSTNAME_VERIFICATION \
  MODEL_REGISTRY_BACKEND \
  PRODUCTION_HEALTH_WEBHOOK_ENABLED \
  PRODUCTION_HEALTH_WEBHOOK_URL \
  PRODUCTION_HEALTH_WEBHOOK_TIMEOUT_SECONDS \
  PRODUCTION_HEALTH_WEBHOOK_BEARER_TOKEN

remove_legacy_secrets \
  "${MONITORING_JOB}" \
  hopsworks-api-key \
  production-health-webhook-url \
  production-health-webhook-token

patch_schedule \
  "${MONITORING_JOB}" \
  "${MONITORING_CRON}" \
  "${MONITORING_TIMEOUT}"

# -----------------------------------------------------------------------------
# Final validation
# -----------------------------------------------------------------------------

echo
echo "============================================================"
echo "Final production job state"
echo "============================================================"

verify_job "${FEATURE_JOB}"
verify_job "${FORECAST_JOB}"
verify_job "${RETRAINING_JOB}"
verify_job "${MONITORING_JOB}"

echo
echo "Checking production jobs for legacy Hopsworks configuration..."

for job_name in \
  "${FEATURE_JOB}" \
  "${FORECAST_JOB}" \
  "${RETRAINING_JOB}" \
  "${MONITORING_JOB}"
do
  legacy_env_count="$(
    az containerapp job show \
      --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
      --name "${job_name}" \
      --query \
        'length(properties.template.containers[0].env[?contains(name, `HOPSWORKS`)])' \
      --output tsv
  )"

  if [[ "${legacy_env_count}" != "0" ]]; then
    echo \
      "Legacy Hopsworks environment variables remain on ${job_name}." \
      >&2
    exit 1
  fi
done

echo
echo "Production scheduled jobs deployed successfully."
echo "Image: ${PIPELINE_IMAGE}"

echo
echo "Schedules (UTC):"
echo "  Features:   ${FEATURE_CRON}"
echo "  Forecast:   ${FORECAST_CRON}"
echo "  Retraining: ${RETRAINING_CRON}"
echo "  Monitoring: ${MONITORING_CRON}"

echo
echo "Production backends:"
echo "  Feature store:  azure_blob"
echo "  Model registry: azure_blob"
echo "  Artifacts:      azure_blob"
echo "  Monitoring:     ARM + Azure Blob + ACS email"

echo
echo "Hopsworks remains available only through non-production/demo configuration."