#!/usr/bin/env bash

set -Eeuo pipefail


RESOURCE_GROUP="${RESOURCE_GROUP:-rg-pearls-aqi-staging}"
LOCATION="${LOCATION:-centralindia}"

API_APP="${API_APP:-ca-pearls-aqi-api-staging}"
DASHBOARD_APP="${DASHBOARD_APP:-ca-pearls-aqi-dashboard-staging}"

IDENTITY_NAME="${IDENTITY_NAME:-id-pearls-aqi-staging}"

STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-stpearlsaqiriyan}"
STORAGE_CONTAINER="${STORAGE_CONTAINER:-artifacts}"

ACR_NAME="${ACR_NAME:-walpole}"
ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-walpole.azurecr.io}"

IMAGE_NAME="${IMAGE_NAME:-pearls-aqi-api}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"

APP_VERSION="${APP_VERSION:-${IMAGE_TAG}}"
GIT_COMMIT="${GIT_COMMIT:-$(git rev-parse HEAD)}"
BUILD_DATE="${BUILD_DATE:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"


echo "Deploying Blob-backed staging API"
echo "Resource group: ${RESOURCE_GROUP}"
echo "Container app: ${API_APP}"
echo "Image tag: ${IMAGE_TAG}"


az account show \
    --query "{
        subscription:name,
        subscriptionId:id
    }" \
    --output table


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


echo "Assigning the staging managed identity to the API."

az containerapp identity assign \
    --name "${API_APP}" \
    --resource-group "${RESOURCE_GROUP}" \
    --user-assigned "${IDENTITY_RESOURCE_ID}" \
    --output none


echo "Checking Blob read access."

ROLE_ASSIGNMENT_COUNT="$(
    az role assignment list \
        --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
        --scope "${STORAGE_RESOURCE_ID}" \
        --role "Storage Blob Data Reader" \
        --query "length(@)" \
        --output tsv
)"

if [[ "${ROLE_ASSIGNMENT_COUNT}" == "0" ]]; then
    az role assignment create \
        --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
        --assignee-principal-type ServicePrincipal \
        --role "Storage Blob Data Reader" \
        --scope "${STORAGE_RESOURCE_ID}" \
        --output none

    echo "Storage Blob Data Reader assigned."
else
    echo "Storage Blob Data Reader already assigned."
fi


echo "Logging in to Azure Container Registry."

az acr login \
    --name "${ACR_NAME}"


FULL_IMAGE_NAME="${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "Building ${FULL_IMAGE_NAME}."

docker build \
    --file Dockerfile.api \
    --build-arg "APP_VERSION=${APP_VERSION}" \
    --build-arg "GIT_COMMIT=${GIT_COMMIT}" \
    --build-arg "BUILD_DATE=${BUILD_DATE}" \
    --tag "${FULL_IMAGE_NAME}" \
    .


echo "Pushing ${FULL_IMAGE_NAME}."

docker push "${FULL_IMAGE_NAME}"


DASHBOARD_FQDN="$(
    az containerapp show \
        --name "${DASHBOARD_APP}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query properties.configuration.ingress.fqdn \
        --output tsv
)"


echo "Updating the staging API."

az containerapp update \
    --name "${API_APP}" \
    --resource-group "${RESOURCE_GROUP}" \
    --image "${FULL_IMAGE_NAME}" \
    --set-env-vars \
        "APP_ENV=staging" \
        "SERVICE_ROLE=api" \
        "AZURE_CLIENT_ID=${IDENTITY_CLIENT_ID}" \
        "PEARLS_API_ENVIRONMENT=staging" \
        "PEARLS_API_APPLICATION_VERSION=${APP_VERSION}" \
        "PEARLS_API_ARTIFACT_BACKEND=azure_blob" \
        "PEARLS_API_ARTIFACT_TYPE=aqi" \
        "PEARLS_API_AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}" \
        "PEARLS_API_AZURE_STORAGE_CONTAINER=${STORAGE_CONTAINER}" \
        "PEARLS_API_PHASE_6_BLOB_CACHE_DIRECTORY=/app/.cache/api/aqi/latest" \
        "PEARLS_API_PHASE_6_LATEST_DIRECTORY=/app/aqi/latest" \
        "PEARLS_API_ARTIFACT_CACHE_SECONDS=60" \
        "PEARLS_API_FORECAST_AGING_THRESHOLD_HOURS=48" \
        "PEARLS_API_FORECAST_STALENESS_THRESHOLD_HOURS=168" \
        "PEARLS_API_ALLOWED_CORS_ORIGINS=[\"https://${DASHBOARD_FQDN}\"]" \
        "PEARLS_API_LOG_LEVEL=INFO" \
    --output none


echo "Waiting for the new API revision."

sleep 10


API_FQDN="$(
    az containerapp show \
        --name "${API_APP}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query properties.configuration.ingress.fqdn \
        --output tsv
)"

echo
echo "API image: ${FULL_IMAGE_NAME}"
echo "API URL: https://${API_FQDN}"
echo "Dashboard URL: https://${DASHBOARD_FQDN}"