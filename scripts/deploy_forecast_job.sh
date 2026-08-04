#!/usr/bin/env bash

set -Eeuo pipefail


ACR_RESOURCE_GROUP="${ACR_RESOURCE_GROUP:-walpole-agent_group}"

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-pearls-aqi-staging}"

CONTAINER_ENVIRONMENT="${CONTAINER_ENVIRONMENT:-cae-pearls-aqi-staging}"
IDENTITY_NAME="${IDENTITY_NAME:-id-pearls-aqi-staging}"
FORECAST_JOB="${FORECAST_JOB:-job-pearls-aqi-forecast}"
ACR_NAME="${ACR_NAME:-walpole}"
ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-walpole.azurecr.io}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-stpearlsaqiriyan}"
STORAGE_CONTAINER="${STORAGE_CONTAINER:-artifacts}"
FORECAST_CRON_EXPRESSION="${FORECAST_CRON_EXPRESSION:-0 */6 * * *}"
PIPELINE_IMAGE_TAG="${PIPELINE_IMAGE_TAG:-latest}"
PIPELINE_IMAGE="${ACR_LOGIN_SERVER}/pearls-aqi/pipeline:${PIPELINE_IMAGE_TAG}"


required_secret_variables=(
    OPENAQ_API_KEY
    HOPSWORKS_API_KEY
    HOPSWORKS_PROJECT
    HOPSWORKS_HOST
)


for variable_name in "${required_secret_variables[@]}"; do
    if [[ -z "${!variable_name:-}" ]]; then
        echo "Required environment variable is missing: ${variable_name}"
        exit 1
    fi
done


echo "Deploying scheduled forecast job"
echo "Resource group: ${RESOURCE_GROUP}"
echo "Environment: ${CONTAINER_ENVIRONMENT}"
echo "Job: ${FORECAST_JOB}"
echo "Image: ${PIPELINE_IMAGE}"
echo "Schedule: ${FORECAST_CRON_EXPRESSION} UTC"


IDENTITY_RESOURCE_ID="$(
    az identity show \
        --name "${IDENTITY_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query id \
        --output tsv
)"

IDENTITY_CLIENT_ID="$(
    az identity show \
        --name "${IDENTITY_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query clientId \
        --output tsv
)"

IDENTITY_PRINCIPAL_ID="$(
    az identity show \
        --name "${IDENTITY_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query principalId \
        --output tsv
)"

STORAGE_RESOURCE_ID="$(
    az storage account show \
        --name "${STORAGE_ACCOUNT}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query id \
        --output tsv
)"

ACR_RESOURCE_ID="$(
    az acr show \
        --name "${ACR_NAME}" \
        --resource-group "${ACR_RESOURCE_GROUP}" \
        --query id \
        --output tsv
)"

echo "ACR resource group: ${ACR_RESOURCE_GROUP}"

az acr repository show \
    --name "${ACR_NAME}" \
    --image "pearls-aqi/pipeline:${PIPELINE_IMAGE_TAG}" \
    --output none

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
        echo "Assigning ${role_name}"

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


# The pipeline writes new run artifacts and the latest pointer.
ensure_role_assignment \
    "Storage Blob Data Contributor" \
    "${STORAGE_RESOURCE_ID}"

# The job pulls its private image from ACR.
ensure_role_assignment \
    "AcrPull" \
    "${ACR_RESOURCE_ID}"


job_exists="$(
    az containerapp job show \
        --name "${FORECAST_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query name \
        --output tsv \
        2>/dev/null \
        || true
)"


if [[ -z "${job_exists}" ]]; then
    echo "Creating scheduled forecast job."

    az containerapp job create \
        --name "${FORECAST_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --environment "${CONTAINER_ENVIRONMENT}" \
        --trigger-type Schedule \
        --cron-expression "${FORECAST_CRON_EXPRESSION}" \
        --replica-timeout 1800 \
        --replica-retry-limit 1 \
        --replica-completion-count 1 \
        --parallelism 1 \
        --cpu 0.5 \
        --memory 1.0Gi \
        --image "${PIPELINE_IMAGE}" \
        --container-name forecast-publisher \
        --mi-user-assigned "${IDENTITY_RESOURCE_ID}" \
        --registry-server "${ACR_LOGIN_SERVER}" \
        --registry-identity "${IDENTITY_RESOURCE_ID}" \
        --secrets \
            "openaq-api-key=${OPENAQ_API_KEY}" \
            "hopsworks-api-key=${HOPSWORKS_API_KEY}" \
        --env-vars \
            "APP_ENV=staging" \
            "SERVICE_ROLE=pipeline" \
            "LOG_LEVEL=INFO" \
            "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
            "ARTIFACT_BACKEND=azure_blob" \
            "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}" \
            "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}" \
            "MODEL_LOADING_MODE=HOPSWORKS_REGISTRY" \
            "FEATURE_STORE_BACKEND=hopsworks" \
            "MODEL_REGISTRY_BACKEND=hopsworks" \
            "HOPSWORKS_PROJECT=${HOPSWORKS_PROJECT}" \
            "HOPSWORKS_HOST=${HOPSWORKS_HOST}" \
            "HOPSWORKS_PORT=443" \
            "HOPSWORKS_ENGINE=python" \
            "HOPSWORKS_API_KEY=secretref:hopsworks-api-key" \
            "OPENAQ_API_KEY=secretref:openaq-api-key" \
            "ALLOW_CACHED_REGISTRY_FALLBACK=true" \
            "ALLOW_LOCAL_MODEL_FALLBACK=true" \
            "AUTOMATIC_RETRAINING_ENABLED=false" \
            "AUTOMATIC_MODEL_PROMOTION_ENABLED=false" \
        --tags \
            "project=pearls-aqi" \
            "environment=staging" \
            "workload=forecast-publication" \
        --output none

else
    echo "Forecast job already exists. Updating it."

    az containerapp job identity assign \
        --name "${FORECAST_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --user-assigned "${IDENTITY_RESOURCE_ID}" \
        --output none

    az containerapp job secret set \
        --name "${FORECAST_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --secrets \
            "openaq-api-key=${OPENAQ_API_KEY}" \
            "hopsworks-api-key=${HOPSWORKS_API_KEY}" \
        --output none

    az containerapp job update \
        --name "${FORECAST_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --image "${PIPELINE_IMAGE}" \
        --cron-expression "${FORECAST_CRON_EXPRESSION}" \
        --replica-timeout 1800 \
        --replica-retry-limit 1 \
        --parallelism 1 \
        --cpu 0.5 \
        --memory 1.0Gi \
        --set-env-vars \
            "APP_ENV=staging" \
            "SERVICE_ROLE=pipeline" \
            "LOG_LEVEL=INFO" \
            "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
            "ARTIFACT_BACKEND=azure_blob" \
            "AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}" \
            "AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}" \
            "MODEL_LOADING_MODE=HOPSWORKS_REGISTRY" \
            "FEATURE_STORE_BACKEND=hopsworks" \
            "MODEL_REGISTRY_BACKEND=hopsworks" \
            "HOPSWORKS_PROJECT=${HOPSWORKS_PROJECT}" \
            "HOPSWORKS_HOST=${HOPSWORKS_HOST}" \
            "HOPSWORKS_PORT=443" \
            "HOPSWORKS_ENGINE=python" \
            "HOPSWORKS_API_KEY=secretref:hopsworks-api-key" \
            "OPENAQ_API_KEY=secretref:openaq-api-key" \
            "ALLOW_CACHED_REGISTRY_FALLBACK=true" \
            "ALLOW_LOCAL_MODEL_FALLBACK=true" \
            "AUTOMATIC_RETRAINING_ENABLED=false" \
            "AUTOMATIC_MODEL_PROMOTION_ENABLED=false" \
        --output none

    az containerapp job registry set \
        --name "${FORECAST_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --server "${ACR_LOGIN_SERVER}" \
        --identity "${IDENTITY_RESOURCE_ID}" \
        --output none
fi


echo
echo "Forecast job deployed successfully."
echo "Job name: ${FORECAST_JOB}"
echo "Schedule: ${FORECAST_CRON_EXPRESSION} UTC"
echo "Image: ${PIPELINE_IMAGE}"