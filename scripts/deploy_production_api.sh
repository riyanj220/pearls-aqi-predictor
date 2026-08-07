#!/usr/bin/env bash

set -Eeuo pipefail


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-pearls-aqi-prod}"

API_APP="${API_APP:-ca-pearls-aqi-api-prod}"

IDENTITY_NAME="${IDENTITY_NAME:-id-pearls-aqi-prod}"

ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-cae-pearls-aqi-staging}"

ENVIRONMENT_RESOURCE_GROUP="${ENVIRONMENT_RESOURCE_GROUP:-rg-pearls-aqi-staging}"

ACR_NAME="${ACR_NAME:-walpole}"

ACR_SERVER="${ACR_SERVER:-walpole.azurecr.io}"

STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-stpearlsaqiriyan}"

STORAGE_CONTAINER="${STORAGE_CONTAINER:-artifacts-prod}"

RELEASE_SHA="${RELEASE_SHA:-$(git rev-parse HEAD)}"


API_IMAGE="${ACR_SERVER}/pearls-aqi/api:${RELEASE_SHA}"


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

echo "Validating production API deployment inputs..."

az account show \
    --output none


if [[ -n "$(git status --porcelain)" ]]; then
    echo \
        "Working tree must be clean before " \
        "production deployment." \
        >&2

    exit 1
fi


if ! az acr repository show \
    --name "${ACR_NAME}" \
    --image "pearls-aqi/api:${RELEASE_SHA}" \
    --output none
then
    echo \
        "Production API image does not exist:" \
        "${API_IMAGE}" \
        >&2

    exit 1
fi


# ---------------------------------------------------------------------------
# Resolve production identity
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Resolve shared Container Apps environment
# ---------------------------------------------------------------------------

ENVIRONMENT_RESOURCE_ID="$(
    az containerapp env show \
        --resource-group \
        "${ENVIRONMENT_RESOURCE_GROUP}" \
        --name "${ENVIRONMENT_NAME}" \
        --query id \
        --output tsv
)"


ENVIRONMENT_STATE="$(
    az containerapp env show \
        --resource-group \
        "${ENVIRONMENT_RESOURCE_GROUP}" \
        --name "${ENVIRONMENT_NAME}" \
        --query properties.provisioningState \
        --output tsv
)"


if [[ "${ENVIRONMENT_STATE}" != "Succeeded" ]]; then
    echo \
        "Shared Container Apps environment " \
        "is not ready: ${ENVIRONMENT_STATE}" \
        >&2

    exit 1
fi


# ---------------------------------------------------------------------------
# Guard against accidental pre-existing production API
# ---------------------------------------------------------------------------

if az containerapp show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${API_APP}" \
    --output none \
    >/dev/null 2>&1
then
    echo \
        "Production API already exists." \
        " Updating immutable release image."

    az containerapp update \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${API_APP}" \
        --image "${API_IMAGE}" \
        --set-env-vars \
            "APP_ENV=production" \
            "SERVICE_ROLE=api" \
            "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
            "PEARLS_API_ENVIRONMENT=production" \
            "PEARLS_API_APPLICATION_VERSION=${RELEASE_SHA}" \
            "PEARLS_API_ARTIFACT_BACKEND=azure_blob" \
            "PEARLS_API_ARTIFACT_TYPE=aqi" \
            "PEARLS_API_AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}" \
            "PEARLS_API_AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}" \
            "PEARLS_API_PHASE_6_BLOB_CACHE_DIRECTORY=/app/.cache/api/aqi/latest" \
            "PEARLS_API_PHASE_6_LATEST_DIRECTORY=/app/aqi/latest" \
            "PEARLS_API_ARTIFACT_CACHE_SECONDS=60" \
            "PEARLS_API_FORECAST_AGING_THRESHOLD_HOURS=7" \
            "PEARLS_API_FORECAST_STALENESS_THRESHOLD_HOURS=13" \
            'PEARLS_API_ALLOWED_CORS_ORIGINS=[]' \
            "PEARLS_API_LOG_LEVEL=INFO" \
        --output none

else

    echo "Creating production FastAPI Container App..."

    az containerapp create \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${API_APP}" \
        --environment "${ENVIRONMENT_RESOURCE_ID}" \
        --image "${API_IMAGE}" \
        --user-assigned "${IDENTITY_RESOURCE_ID}" \
        --registry-server "${ACR_SERVER}" \
        --registry-identity "${IDENTITY_RESOURCE_ID}" \
        --ingress external \
        --target-port 8000 \
        --transport auto \
        --cpu 0.25 \
        --memory 0.5Gi \
        --min-replicas 0 \
        --max-replicas 1 \
        --env-vars \
            "APP_ENV=production" \
            "SERVICE_ROLE=api" \
            "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
            "PEARLS_API_ENVIRONMENT=production" \
            "PEARLS_API_APPLICATION_VERSION=${RELEASE_SHA}" \
            "PEARLS_API_ARTIFACT_BACKEND=azure_blob" \
            "PEARLS_API_ARTIFACT_TYPE=aqi" \
            "PEARLS_API_AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}" \
            "PEARLS_API_AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}" \
            "PEARLS_API_PHASE_6_BLOB_CACHE_DIRECTORY=/app/.cache/api/aqi/latest" \
            "PEARLS_API_PHASE_6_LATEST_DIRECTORY=/app/aqi/latest" \
            "PEARLS_API_ARTIFACT_CACHE_SECONDS=60" \
            "PEARLS_API_FORECAST_AGING_THRESHOLD_HOURS=7" \
            "PEARLS_API_FORECAST_STALENESS_THRESHOLD_HOURS=13" \
            'PEARLS_API_ALLOWED_CORS_ORIGINS=[]' \
            "PEARLS_API_LOG_LEVEL=INFO" \
        --tags \
            "project=pearls-aqi" \
            "environment=production" \
            "service=api" \
            "release=${RELEASE_SHA}" \
        --output none
fi


# ---------------------------------------------------------------------------
# Wait for provisioning
# ---------------------------------------------------------------------------

echo "Waiting for production API provisioning..."

for _ in $(seq 1 60); do
    state="$(
        az containerapp show \
            --resource-group "${RESOURCE_GROUP}" \
            --name "${API_APP}" \
            --query properties.provisioningState \
            --output tsv \
            2>/dev/null \
            || true
    )"

    echo "Provisioning state: ${state:-unknown}"

    case "${state}" in
        Succeeded)
            break
            ;;

        Failed|Canceled)
            echo \
                "Production API provisioning failed." \
                >&2

            exit 1
            ;;
    esac

    sleep 10
done


API_FQDN="$(
    az containerapp show \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${API_APP}" \
        --query properties.configuration.ingress.fqdn \
        --output tsv
)"


if [[ -z "${API_FQDN}" ]]; then
    echo \
        "Production API FQDN was not assigned." \
        >&2

    exit 1
fi


echo
echo "Production API deployed."
echo "Application: ${API_APP}"
echo "Image:       ${API_IMAGE}"
echo "URL:         https://${API_FQDN}"
echo "Liveness:    https://${API_FQDN}/api/v1/health/live"
echo "Readiness:   https://${API_FQDN}/api/v1/health/ready"
echo
echo \
    "Readiness is expected to return HTTP 503 " \
    "until the first production AQI artifact is published."