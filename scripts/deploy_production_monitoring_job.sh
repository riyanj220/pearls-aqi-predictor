#!/usr/bin/env bash

set -euo pipefail

# -----------------------------------------------------------------------------
# Production monitoring job deployment
# -----------------------------------------------------------------------------

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-pearls-aqi-prod}"

# Production jobs reuse the shared Container Apps Environment because the
# Azure for Students subscription only allows one environment.
ENVIRONMENT="${AZURE_CONTAINER_APP_ENVIRONMENT:-cae-pearls-aqi-staging}"

JOB_NAME="${AZURE_MONITORING_JOB_NAME:-job-pearls-aqi-monitoring-prod}"
CRON_EXPRESSION="${AZURE_MONITORING_CRON:-45 * * * *}"

IDENTITY_NAME="${AZURE_MANAGED_IDENTITY_NAME:-id-pearls-aqi-prod}"

ACR_NAME="${AZURE_ACR_NAME:-walpole}"
ACR_SERVER="${AZURE_ACR_SERVER:-walpole.azurecr.io}"
IMAGE_REPOSITORY="${AZURE_PIPELINE_IMAGE_REPOSITORY:-pearls-aqi/pipeline}"

STORAGE_ACCOUNT="${AZURE_STORAGE_ACCOUNT:-stpearlsaqiriyan}"
STORAGE_CONTAINER="${AZURE_STORAGE_CONTAINER:-artifacts-prod}"
FEATURE_STORE_PREFIX="${AZURE_FEATURE_STORE_PREFIX:-feature-store}"

FEATURE_JOB_NAME="${AZURE_FEATURE_JOB_NAME:-job-pearls-aqi-features-prod}"
FORECAST_JOB_NAME="${AZURE_FORECAST_JOB_NAME:-job-pearls-aqi-forecast-prod}"
RETRAINING_JOB_NAME="${AZURE_RETRAINING_JOB_NAME:-job-pearls-aqi-retraining-prod}"

IMAGE_TAG="${PIPELINE_IMAGE_TAG:-$(git rev-parse HEAD)}"
IMAGE="${ACR_SERVER}/${IMAGE_REPOSITORY}:${IMAGE_TAG}"

SUBSCRIPTION_ID="$(
  az account show \
    --query id \
    --output tsv
)"

# -----------------------------------------------------------------------------
# Required runtime configuration
# -----------------------------------------------------------------------------

required_variables=(
  PRODUCTION_HEALTH_EMAIL_ENDPOINT
  PRODUCTION_HEALTH_EMAIL_SENDER
  PRODUCTION_HEALTH_EMAIL_RECIPIENT
)

for variable_name in "${required_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "Missing required variable: ${variable_name}" >&2
    exit 1
  fi
done

# -----------------------------------------------------------------------------
# Managed identity
# -----------------------------------------------------------------------------

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

# -----------------------------------------------------------------------------
# RBAC
# -----------------------------------------------------------------------------

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
    echo "Assigning ${role_name} at ${scope}"

    az role assignment create \
      --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
      --assignee-principal-type ServicePrincipal \
      --role "${role_name}" \
      --scope "${scope}" \
      --output none
  fi
}

# Required so the monitoring process can inspect Container Apps Job executions.
ensure_role_assignment \
  "Reader" \
  "${RESOURCE_GROUP_ID}"

# -----------------------------------------------------------------------------
# Validate immutable pipeline image exists
# -----------------------------------------------------------------------------

if ! az acr repository show \
  --name "${ACR_NAME}" \
  --image "${IMAGE_REPOSITORY}:${IMAGE_TAG}" \
  --output none
then
  echo "Image does not exist: ${IMAGE}" >&2
  exit 1
fi

echo "Using image: ${IMAGE}"

# -----------------------------------------------------------------------------
# Common runtime configuration
# -----------------------------------------------------------------------------

ENV_VARS=(
  "APP_ENV=production"
  "SERVICE_ROLE=monitoring"

  "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}"
  "AZURE_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}"
  "AZURE_JOB_QUERY_BACKEND=arm"

  "PRODUCTION_RESOURCE_GROUP=${RESOURCE_GROUP}"
  "FEATURE_JOB_NAME=${FEATURE_JOB_NAME}"
  "FORECAST_JOB_NAME=${FORECAST_JOB_NAME}"
  "RETRAINING_JOB_NAME=${RETRAINING_JOB_NAME}"

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

# -----------------------------------------------------------------------------
# Create or update monitoring job
# -----------------------------------------------------------------------------

if az containerapp job show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${JOB_NAME}" \
  --output none \
  >/dev/null 2>&1
then
  echo "Updating existing monitoring job: ${JOB_NAME}"

  # Keep the recipient private in the Container Apps secret store.
  az containerapp job secret set \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${JOB_NAME}" \
    --secrets \
      "production-health-email-recipient=${PRODUCTION_HEALTH_EMAIL_RECIPIENT}" \
    --output none

  az containerapp job update \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${JOB_NAME}" \
    --image "${IMAGE}" \
    --cpu 0.5 \
    --memory 1.0Gi \
    --set-env-vars "${ENV_VARS[@]}" \
    --tags \
      "project=pearls-aqi" \
      "environment=production" \
      "workload=production-monitoring" \
      "release=${IMAGE_TAG}" \
    --output none

else
  echo "Creating monitoring job: ${JOB_NAME}"

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
      "production-health-email-recipient=${PRODUCTION_HEALTH_EMAIL_RECIPIENT}" \
    --env-vars "${ENV_VARS[@]}" \
    --tags \
      "project=pearls-aqi" \
      "environment=production" \
      "workload=production-monitoring" \
      "release=${IMAGE_TAG}" \
    --output none
fi

# -----------------------------------------------------------------------------
# Ensure the job remains scheduled
#
# Some Container Apps CLI versions preserve an existing Manual trigger when
# using `job update`. Patch the trigger explicitly so this script is
# deterministic across CLI versions.
# -----------------------------------------------------------------------------

az rest \
  --method PATCH \
  --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.App/jobs/${JOB_NAME}?api-version=2025-07-01" \
  --headers "Content-Type=application/json" \
  --body "{
    \"properties\": {
      \"configuration\": {
        \"triggerType\": \"Schedule\",
        \"scheduleTriggerConfig\": {
          \"cronExpression\": \"${CRON_EXPRESSION}\",
          \"parallelism\": 1,
          \"replicaCompletionCount\": 1
        }
      }
    }
  }" \
  --output none

# -----------------------------------------------------------------------------
# Remove obsolete legacy configuration
# -----------------------------------------------------------------------------

# Ignore failures here so the script is safe both for old and already-clean
# monitoring jobs.
az containerapp job update \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${JOB_NAME}" \
  --remove-env-vars \
    HOPSWORKS_API_KEY \
    HOPSWORKS_PROJECT \
    HOPSWORKS_HOST \
    MODEL_REGISTRY_BACKEND \
    PRODUCTION_HEALTH_WEBHOOK_ENABLED \
    PRODUCTION_HEALTH_WEBHOOK_URL \
    PRODUCTION_HEALTH_WEBHOOK_TIMEOUT_SECONDS \
  --output none \
  2>/dev/null || true

az containerapp job secret remove \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${JOB_NAME}" \
  --secret-names \
    hopsworks-api-key \
    production-health-webhook-url \
  --output none \
  2>/dev/null || true

# -----------------------------------------------------------------------------
# Final deployment verification
# -----------------------------------------------------------------------------

echo
echo "Verifying deployed monitoring job..."

az containerapp job show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${JOB_NAME}" \
  --query '{
    provisioningState:properties.provisioningState,
    triggerType:properties.configuration.triggerType,
    cron:properties.configuration.scheduleTriggerConfig.cronExpression,
    image:properties.template.containers[0].image,
    command:properties.template.containers[0].command
  }' \
  --output json

echo
echo "Production monitoring job deployed successfully."
echo "Job: ${JOB_NAME}"
echo "Schedule: ${CRON_EXPRESSION} UTC"
echo "Image: ${IMAGE}"
echo "Feature backend: azure_blob"
echo "Artifact backend: azure_blob"
echo "Notification channel: email"