#!/usr/bin/env bash

set -Eeuo pipefail


RESOURCE_GROUP="${RESOURCE_GROUP:-rg-pearls-aqi-staging}"
CONTAINER_ENVIRONMENT="${CONTAINER_ENVIRONMENT:-cae-pearls-aqi-staging}"
IDENTITY_NAME="${IDENTITY_NAME:-id-pearls-aqi-staging}"

FEATURE_JOB="${FEATURE_JOB:-job-pearls-aqi-features}"
FEATURE_CRON_EXPRESSION="${FEATURE_CRON_EXPRESSION:-15 * * * *}"

ACR_NAME="${ACR_NAME:-walpole}"
ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-walpole.azurecr.io}"

PIPELINE_REPOSITORY="${PIPELINE_REPOSITORY:-pearls-aqi/pipeline}"
PIPELINE_IMAGE_TAG="${PIPELINE_IMAGE_TAG:-}"
PIPELINE_IMAGE="${ACR_LOGIN_SERVER}/${PIPELINE_REPOSITORY}:${PIPELINE_IMAGE_TAG}"


required_variables=(
    PIPELINE_IMAGE_TAG
    OPENAQ_API_KEY
    HOPSWORKS_API_KEY
    HOPSWORKS_PROJECT
    HOPSWORKS_HOST
)


for variable_name in "${required_variables[@]}"; do
    if [[ -z "${!variable_name:-}" ]]; then
        echo "Required environment variable is missing: ${variable_name}" >&2
        exit 1
    fi
done


echo "Deploying hourly feature synchronization job"
echo "Resource group: ${RESOURCE_GROUP}"
echo "Container Apps environment: ${CONTAINER_ENVIRONMENT}"
echo "Job name: ${FEATURE_JOB}"
echo "Schedule: ${FEATURE_CRON_EXPRESSION} UTC"
echo "Image: ${PIPELINE_IMAGE}"


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

ACR_RESOURCE_ID="$(
    az acr show \
        --name "${ACR_NAME}" \
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
        echo "Assigning ${role_name}."

        az role assignment create \
            --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
            --assignee-principal-type ServicePrincipal \
            --role "${role_name}" \
            --scope "${scope}" \
            --output none
    else
        echo "${role_name} is already assigned."
    fi
}


# The job requires this role only to pull its private image.
ensure_role_assignment \
    "AcrPull" \
    "${ACR_RESOURCE_ID}"


job_exists="$(
    az containerapp job show \
        --name "${FEATURE_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query name \
        --output tsv \
        2>/dev/null \
        || true
)"


if [[ -z "${job_exists}" ]]; then
    echo "Creating hourly feature synchronization job."

    az containerapp job create \
        --name "${FEATURE_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --environment "${CONTAINER_ENVIRONMENT}" \
        --trigger-type Schedule \
        --cron-expression "${FEATURE_CRON_EXPRESSION}" \
        --replica-timeout 900 \
        --replica-retry-limit 1 \
        --replica-completion-count 1 \
        --parallelism 1 \
        --cpu 0.5 \
        --memory 1.0Gi \
        --image "${PIPELINE_IMAGE}" \
        --container-name hourly-features \
        --command "/app/bin/run_hourly_features" \
        --mi-user-assigned "${IDENTITY_RESOURCE_ID}" \
        --registry-server "${ACR_LOGIN_SERVER}" \
        --registry-identity "${IDENTITY_RESOURCE_ID}" \
        --secrets \
            "openaq-api-key=${OPENAQ_API_KEY}" \
            "hopsworks-api-key=${HOPSWORKS_API_KEY}" \
        --env-vars \
            "APP_ENV=staging" \
            "SERVICE_ROLE=hourly-features" \
            "LOG_LEVEL=INFO" \
            "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
            "OPENAQ_API_KEY=secretref:openaq-api-key" \
            "HOPSWORKS_API_KEY=secretref:hopsworks-api-key" \
            "HOPSWORKS_PROJECT=${HOPSWORKS_PROJECT}" \
            "HOPSWORKS_HOST=${HOPSWORKS_HOST}" \
            "HOPSWORKS_PORT=443" \
            "HOPSWORKS_ENGINE=python" \
            "HOPSWORKS_HOSTNAME_VERIFICATION=true" \
            "FEATURE_STORE_BACKEND=hopsworks" \
            "MODEL_REGISTRY_BACKEND=hopsworks" \
            "MLOPS_DRY_RUN=false" \
            "INCREMENTAL_OVERLAP_HOURS=30" \
            "INCREMENTAL_INITIAL_LOOKBACK_HOURS=168" \
            "AUTOMATIC_RETRAINING_ENABLED=false" \
            "AUTOMATIC_MODEL_PROMOTION_ENABLED=false" \
        --tags \
            "project=pearls-aqi" \
            "environment=staging" \
            "workload=hourly-feature-sync" \
        --output none

else
    echo "Hourly feature job already exists. Updating it."

    az containerapp job identity assign \
        --name "${FEATURE_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --user-assigned "${IDENTITY_RESOURCE_ID}" \
        --output none

    az containerapp job secret set \
        --name "${FEATURE_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --secrets \
            "openaq-api-key=${OPENAQ_API_KEY}" \
            "hopsworks-api-key=${HOPSWORKS_API_KEY}" \
        --output none

    az containerapp job update \
        --name "${FEATURE_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --image "${PIPELINE_IMAGE}" \
        --cron-expression "${FEATURE_CRON_EXPRESSION}" \
        --replica-timeout 900 \
        --replica-retry-limit 1 \
        --replica-completion-count 1 \
        --parallelism 1 \
        --cpu 0.5 \
        --memory 1.0Gi \
        --command "/app/bin/run_hourly_features" \
        --set-env-vars \
            "APP_ENV=staging" \
            "SERVICE_ROLE=hourly-features" \
            "LOG_LEVEL=INFO" \
            "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
            "OPENAQ_API_KEY=secretref:openaq-api-key" \
            "HOPSWORKS_API_KEY=secretref:hopsworks-api-key" \
            "HOPSWORKS_PROJECT=${HOPSWORKS_PROJECT}" \
            "HOPSWORKS_HOST=${HOPSWORKS_HOST}" \
            "HOPSWORKS_PORT=443" \
            "HOPSWORKS_ENGINE=python" \
            "HOPSWORKS_HOSTNAME_VERIFICATION=true" \
            "FEATURE_STORE_BACKEND=hopsworks" \
            "MODEL_REGISTRY_BACKEND=hopsworks" \
            "MLOPS_DRY_RUN=false" \
            "INCREMENTAL_OVERLAP_HOURS=30" \
            "INCREMENTAL_INITIAL_LOOKBACK_HOURS=168" \
            "AUTOMATIC_RETRAINING_ENABLED=false" \
            "AUTOMATIC_MODEL_PROMOTION_ENABLED=false" \
        --output none

    az containerapp job registry set \
        --name "${FEATURE_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --server "${ACR_LOGIN_SERVER}" \
        --identity "${IDENTITY_RESOURCE_ID}" \
        --output none
fi


echo
echo "Hourly feature synchronization job deployed."
echo "Job: ${FEATURE_JOB}"
echo "Schedule: ${FEATURE_CRON_EXPRESSION} UTC"
echo "Image: ${PIPELINE_IMAGE}"