#!/usr/bin/env bash

set -Eeuo pipefail


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PRODUCTION_RESOURCE_GROUP="${PRODUCTION_RESOURCE_GROUP:-rg-pearls-aqi-prod}"

SOURCE_RESOURCE_GROUP="${SOURCE_RESOURCE_GROUP:-rg-pearls-aqi-staging}"

ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-cae-pearls-aqi-staging}"

ENVIRONMENT_RESOURCE_GROUP="${ENVIRONMENT_RESOURCE_GROUP:-rg-pearls-aqi-staging}"

IDENTITY_NAME="${IDENTITY_NAME:-id-pearls-aqi-prod}"

ACR_NAME="${ACR_NAME:-walpole}"
ACR_SERVER="${ACR_SERVER:-walpole.azurecr.io}"

STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-stpearlsaqiriyan}"

STORAGE_CONTAINER="${STORAGE_CONTAINER:-artifacts-prod}"

RELEASE_SHA="${RELEASE_SHA:-$(git rev-parse HEAD)}"

PIPELINE_IMAGE="${ACR_SERVER}/pearls-aqi/pipeline:${RELEASE_SHA}"


SOURCE_FEATURE_JOB="job-pearls-aqi-features"
SOURCE_FORECAST_JOB="job-pearls-aqi-forecast"
SOURCE_RETRAINING_JOB="job-pearls-aqi-retraining"
SOURCE_MONITORING_JOB="job-pearls-aqi-monitoring"

FEATURE_JOB="job-pearls-aqi-features-prod"
FORECAST_JOB="job-pearls-aqi-forecast-prod"
RETRAINING_JOB="job-pearls-aqi-retraining-prod"
MONITORING_JOB="job-pearls-aqi-monitoring-prod"


# ---------------------------------------------------------------------------
# Required secrets
# ---------------------------------------------------------------------------

required_variables=(
    OPENAQ_API_KEY
    HOPSWORKS_API_KEY
    HOPSWORKS_PROJECT
    HOPSWORKS_HOST
)

for variable_name in "${required_variables[@]}"; do
    if [[ -z "${!variable_name:-}" ]]; then
        echo \
            "Missing required variable: ${variable_name}" \
            >&2

        exit 1
    fi
done


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

echo "Validating production scheduled-job deployment..."

az account show \
    --output none


if [[ -n "$(git status --porcelain)" ]]; then
    echo \
        "Working tree must be clean before production deployment." \
        >&2

    exit 1
fi


if ! az acr repository show \
    --name "${ACR_NAME}" \
    --image "pearls-aqi/pipeline:${RELEASE_SHA}" \
    --output none
then
    echo \
        "Production pipeline image does not exist: " \
        "${PIPELINE_IMAGE}" \
        >&2

    exit 1
fi


# ---------------------------------------------------------------------------
# Resolve Azure infrastructure
# ---------------------------------------------------------------------------

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


SUBSCRIPTION_ID="$(
    az account show \
        --query id \
        --output tsv
)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

source_value() {
    local job_name="$1"
    local query="$2"

    az containerapp job show \
        --resource-group "${SOURCE_RESOURCE_GROUP}" \
        --name "${job_name}" \
        --query "${query}" \
        --output tsv
}


delete_existing_job() {
    local job_name="$1"

    if az containerapp job show \
        --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
        --name "${job_name}" \
        --output none \
        >/dev/null 2>&1
    then
        echo "Deleting existing ${job_name}..."

        az containerapp job delete \
            --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
            --name "${job_name}" \
            --yes \
            --output none
    fi
}


# ---------------------------------------------------------------------------
# Resolve proven staging resource profiles
# ---------------------------------------------------------------------------

FEATURE_CPU="$(
    source_value \
        "${SOURCE_FEATURE_JOB}" \
        'properties.template.containers[0].resources.cpu'
)"

FEATURE_MEMORY="$(
    source_value \
        "${SOURCE_FEATURE_JOB}" \
        'properties.template.containers[0].resources.memory'
)"


FORECAST_CPU="$(
    source_value \
        "${SOURCE_FORECAST_JOB}" \
        'properties.template.containers[0].resources.cpu'
)"

FORECAST_MEMORY="$(
    source_value \
        "${SOURCE_FORECAST_JOB}" \
        'properties.template.containers[0].resources.memory'
)"


RETRAINING_CPU="$(
    source_value \
        "${SOURCE_RETRAINING_JOB}" \
        'properties.template.containers[0].resources.cpu'
)"

RETRAINING_MEMORY="$(
    source_value \
        "${SOURCE_RETRAINING_JOB}" \
        'properties.template.containers[0].resources.memory'
)"


MONITORING_CPU="$(
    source_value \
        "${SOURCE_MONITORING_JOB}" \
        'properties.template.containers[0].resources.cpu'
)"

MONITORING_MEMORY="$(
    source_value \
        "${SOURCE_MONITORING_JOB}" \
        'properties.template.containers[0].resources.memory'
)"


echo
echo "Resolved workload profiles:"
echo \
    "Features:   ${FEATURE_CPU} CPU / ${FEATURE_MEMORY}"
echo \
    "Forecast:   ${FORECAST_CPU} CPU / ${FORECAST_MEMORY}"
echo \
    "Retraining: ${RETRAINING_CPU} CPU / ${RETRAINING_MEMORY}"
echo \
    "Monitoring: ${MONITORING_CPU} CPU / ${MONITORING_MEMORY}"


# ---------------------------------------------------------------------------
# Hourly features
# ---------------------------------------------------------------------------

delete_existing_job "${FEATURE_JOB}"

echo
echo "Creating production hourly feature job..."

az containerapp job create \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${FEATURE_JOB}" \
    --environment "${ENVIRONMENT_RESOURCE_ID}" \
    --trigger-type Schedule \
    --cron-expression "15 * * * *" \
    --replica-timeout 900 \
    --replica-retry-limit 1 \
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
        "hopsworks-api-key=${HOPSWORKS_API_KEY}" \
    --env-vars \
        "APP_ENV=production" \
        "SERVICE_ROLE=hourly_features" \
        "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
        "FEATURE_STORE_BACKEND=hopsworks" \
        "MODEL_REGISTRY_BACKEND=hopsworks" \
        "MLOPS_DRY_RUN=false" \
        "OPENAQ_API_KEY=secretref:openaq-api-key" \
        "HOPSWORKS_API_KEY=secretref:hopsworks-api-key" \
        "HOPSWORKS_PROJECT=${HOPSWORKS_PROJECT}" \
        "HOPSWORKS_HOST=${HOPSWORKS_HOST}" \
    --tags \
        "project=pearls-aqi" \
        "environment=production" \
        "workload=hourly-features" \
        "release=${RELEASE_SHA}" \
    --output none


# ---------------------------------------------------------------------------
# Forecast publication
# ---------------------------------------------------------------------------

delete_existing_job "${FORECAST_JOB}"

echo
echo "Creating production forecast job..."

az containerapp job create \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${FORECAST_JOB}" \
    --environment "${ENVIRONMENT_RESOURCE_ID}" \
    --trigger-type Schedule \
    --cron-expression "0 */6 * * *" \
    --replica-timeout 1800 \
    --replica-retry-limit 1 \
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
        "hopsworks-api-key=${HOPSWORKS_API_KEY}" \
    --env-vars \
        "APP_ENV=production" \
        "SERVICE_ROLE=forecast" \
        "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
        "ARTIFACT_BACKEND=azure_blob" \
        "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}" \
        "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}" \
        "FEATURE_STORE_BACKEND=hopsworks" \
        "MODEL_REGISTRY_BACKEND=hopsworks" \
        "MLOPS_DRY_RUN=false" \
        "OPENAQ_API_KEY=secretref:openaq-api-key" \
        "HOPSWORKS_API_KEY=secretref:hopsworks-api-key" \
        "HOPSWORKS_PROJECT=${HOPSWORKS_PROJECT}" \
        "HOPSWORKS_HOST=${HOPSWORKS_HOST}" \
    --tags \
        "project=pearls-aqi" \
        "environment=production" \
        "workload=forecast-publication" \
        "release=${RELEASE_SHA}" \
    --output none


# ---------------------------------------------------------------------------
# Daily retraining
# ---------------------------------------------------------------------------

delete_existing_job "${RETRAINING_JOB}"

echo
echo "Creating production daily retraining job..."

az containerapp job create \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${RETRAINING_JOB}" \
    --environment "${ENVIRONMENT_RESOURCE_ID}" \
    --trigger-type Schedule \
    --cron-expression "30 3 * * *" \
    --replica-timeout 3600 \
    --replica-retry-limit 1 \
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
    --secrets \
        "hopsworks-api-key=${HOPSWORKS_API_KEY}" \
    --env-vars \
        "APP_ENV=production" \
        "SERVICE_ROLE=retraining" \
        "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
        "ARTIFACT_BACKEND=azure_blob" \
        "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}" \
        "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}" \
        "FEATURE_STORE_BACKEND=hopsworks" \
        "MODEL_REGISTRY_BACKEND=hopsworks" \
        "MLOPS_DRY_RUN=false" \
        "HOPSWORKS_API_KEY=secretref:hopsworks-api-key" \
        "HOPSWORKS_PROJECT=${HOPSWORKS_PROJECT}" \
        "HOPSWORKS_HOST=${HOPSWORKS_HOST}" \
    --tags \
        "project=pearls-aqi" \
        "environment=production" \
        "workload=daily-retraining" \
        "release=${RELEASE_SHA}" \
    --output none


# ---------------------------------------------------------------------------
# Production monitoring
# ---------------------------------------------------------------------------

delete_existing_job "${MONITORING_JOB}"

echo
echo "Creating production monitoring job..."

monitoring_secrets=(
    "hopsworks-api-key=${HOPSWORKS_API_KEY}"
)

monitoring_env=(
    "APP_ENV=production"
    "SERVICE_ROLE=monitoring"
    "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}"
    "AZURE_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}"
    "AZURE_JOB_QUERY_BACKEND=arm"
    "FEATURE_STORE_BACKEND=hopsworks"
    "MODEL_REGISTRY_BACKEND=hopsworks"
    "MLOPS_DRY_RUN=false"
    "HOPSWORKS_API_KEY=secretref:hopsworks-api-key"
    "HOPSWORKS_PROJECT=${HOPSWORKS_PROJECT}"
    "HOPSWORKS_HOST=${HOPSWORKS_HOST}"
    "ARTIFACT_BACKEND=azure_blob"
    "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}"
    "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}"
    "PRODUCTION_HEALTH_WEBHOOK_ENABLED=true"
    "PRODUCTION_HEALTH_WEBHOOK_URL=secretref:production-health-webhook-url"
    "PRODUCTION_HEALTH_WEBHOOK_TIMEOUT_SECONDS=15"
)

if [[ -n "${PRODUCTION_HEALTH_WEBHOOK_URL:-}" ]]; then
    monitoring_secrets+=(
        "production-health-webhook-url=${PRODUCTION_HEALTH_WEBHOOK_URL}"
    )

    monitoring_env+=(
        "PRODUCTION_HEALTH_WEBHOOK_ENABLED=true"
        "PRODUCTION_HEALTH_WEBHOOK_URL=secretref:production-health-webhook-url"
    )
fi

if [[ -n "${PRODUCTION_HEALTH_WEBHOOK_BEARER_TOKEN:-}" ]]; then
    monitoring_secrets+=(
        "production-health-webhook-token=${PRODUCTION_HEALTH_WEBHOOK_BEARER_TOKEN}"
    )

    monitoring_env+=(
        "PRODUCTION_HEALTH_WEBHOOK_BEARER_TOKEN=secretref:production-health-webhook-token"
    )
fi


az containerapp job create \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --name "${MONITORING_JOB}" \
    --environment "${ENVIRONMENT_RESOURCE_ID}" \
    --trigger-type Schedule \
    --cron-expression "45 * * * *" \
    --replica-timeout 600 \
    --replica-retry-limit 1 \
    --replica-completion-count 1 \
    --parallelism 1 \
    --cpu "${MONITORING_CPU}" \
    --memory "${MONITORING_MEMORY}" \
    --image "${PIPELINE_IMAGE}" \
    --container-name production-monitor \
    --command "python" \
    --args \
        "-m" \
        "app.operations.persist_production_health" \
        "--resource-group" \
        "${PRODUCTION_RESOURCE_GROUP}" \
        "--feature-job-name" \
        "${FEATURE_JOB}" \
        "--forecast-job-name" \
        "${FORECAST_JOB}" \
        "--retraining-job-name" \
        "${RETRAINING_JOB}" \
    --mi-user-assigned "${IDENTITY_RESOURCE_ID}" \
    --registry-server "${ACR_SERVER}" \
    --registry-identity "${IDENTITY_RESOURCE_ID}" \
    --secrets "${monitoring_secrets[@]}" \
    --env-vars "${monitoring_env[@]}" \
    --tags \
        "project=pearls-aqi" \
        "environment=production" \
        "workload=production-monitoring" \
        "release=${RELEASE_SHA}" \
    --output none


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo
echo "Production scheduled jobs deployed."
echo
echo "Image:"
echo "  ${PIPELINE_IMAGE}"
echo
echo "Jobs:"
echo "  ${FEATURE_JOB}"
echo "  ${FORECAST_JOB}"
echo "  ${RETRAINING_JOB}"
echo "  ${MONITORING_JOB}"
echo
echo "Artifact container:"
echo "  ${STORAGE_CONTAINER}"