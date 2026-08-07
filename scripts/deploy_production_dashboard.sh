#!/usr/bin/env bash

set -Eeuo pipefail


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-pearls-aqi-prod}"

DASHBOARD_APP="${DASHBOARD_APP:-ca-pearls-aqi-dashboard-prod}"

API_APP="${API_APP:-ca-pearls-aqi-api-prod}"

IDENTITY_NAME="${IDENTITY_NAME:-id-pearls-aqi-prod}"

ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-cae-pearls-aqi-staging}"

ENVIRONMENT_RESOURCE_GROUP="${ENVIRONMENT_RESOURCE_GROUP:-rg-pearls-aqi-staging}"

ACR_NAME="${ACR_NAME:-walpole}"

ACR_SERVER="${ACR_SERVER:-walpole.azurecr.io}"

RELEASE_SHA="${RELEASE_SHA:-$(git rev-parse HEAD)}"

DASHBOARD_IMAGE="${ACR_SERVER}/pearls-aqi/dashboard:${RELEASE_SHA}"


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

echo "Validating production dashboard deployment inputs..."

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
    --image \
        "pearls-aqi/dashboard:${RELEASE_SHA}" \
    --output none
then
    echo \
        "Production dashboard image does not exist:" \
        "${DASHBOARD_IMAGE}" \
        >&2

    exit 1
fi


# ---------------------------------------------------------------------------
# Resolve production API
# ---------------------------------------------------------------------------

API_FQDN="$(
    az containerapp show \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${API_APP}" \
        --query \
            properties.configuration.ingress.fqdn \
        --output tsv
)"


if [[ -z "${API_FQDN}" ]]; then
    echo \
        "Production API FQDN could not be resolved." \
        >&2

    exit 1
fi


API_BASE_URL="https://${API_FQDN}/api/v1"

echo "Production API:"
echo "  ${API_BASE_URL}"


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
        "Shared Container Apps environment is not ready: " \
        "${ENVIRONMENT_STATE}" \
        >&2

    exit 1
fi


# ---------------------------------------------------------------------------
# Create or update dashboard
# ---------------------------------------------------------------------------

if az containerapp show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${DASHBOARD_APP}" \
    --output none \
    >/dev/null 2>&1
then
    echo "Updating existing production dashboard..."

    az containerapp update \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${DASHBOARD_APP}" \
        --image "${DASHBOARD_IMAGE}" \
        --set-env-vars \
            "DASHBOARD_ENVIRONMENT=production" \
            "FASTAPI_BASE_URL=${API_BASE_URL}" \
            "DASHBOARD_REQUEST_TIMEOUT_SECONDS=10" \
            "DASHBOARD_CACHE_TTL_SECONDS=60" \
            "DASHBOARD_DEFAULT_TIMEZONE=Asia/Karachi" \
        --output none

else
    echo "Creating production Streamlit Container App..."

    az containerapp create \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${DASHBOARD_APP}" \
        --environment "${ENVIRONMENT_RESOURCE_ID}" \
        --image "${DASHBOARD_IMAGE}" \
        --user-assigned "${IDENTITY_RESOURCE_ID}" \
        --registry-server "${ACR_SERVER}" \
        --registry-identity "${IDENTITY_RESOURCE_ID}" \
        --ingress external \
        --target-port 8501 \
        --transport auto \
        --cpu 0.25 \
        --memory 0.5Gi \
        --min-replicas 0 \
        --max-replicas 1 \
        --env-vars \
            "DASHBOARD_ENVIRONMENT=production" \
            "FASTAPI_BASE_URL=${API_BASE_URL}" \
            "DASHBOARD_REQUEST_TIMEOUT_SECONDS=10" \
            "DASHBOARD_CACHE_TTL_SECONDS=60" \
            "DASHBOARD_DEFAULT_TIMEZONE=Asia/Karachi" \
        --tags \
            "project=pearls-aqi" \
            "environment=production" \
            "service=dashboard" \
            "release=${RELEASE_SHA}" \
        --output none
fi


# ---------------------------------------------------------------------------
# Wait for provisioning
# ---------------------------------------------------------------------------

echo "Waiting for production dashboard provisioning..."

provisioned="false"

for _ in $(seq 1 60); do

    state="$(
        az containerapp show \
            --resource-group "${RESOURCE_GROUP}" \
            --name "${DASHBOARD_APP}" \
            --query properties.provisioningState \
            --output tsv \
            2>/dev/null \
            || true
    )"

    echo \
        "Provisioning state: ${state:-unknown}"

    case "${state}" in
        Succeeded)
            provisioned="true"
            break
            ;;

        Failed|Canceled)
            echo \
                "Production dashboard provisioning failed." \
                >&2

            exit 1
            ;;
    esac

    sleep 10
done


if [[ "${provisioned}" != "true" ]]; then
    echo \
        "Timed out waiting for dashboard provisioning." \
        >&2

    exit 1
fi


# ---------------------------------------------------------------------------
# Resolve dashboard FQDN
# ---------------------------------------------------------------------------

DASHBOARD_FQDN="$(
    az containerapp show \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${DASHBOARD_APP}" \
        --query \
            properties.configuration.ingress.fqdn \
        --output tsv
)"


if [[ -z "${DASHBOARD_FQDN}" ]]; then
    echo \
        "Production dashboard FQDN was not assigned." \
        >&2

    exit 1
fi


# ---------------------------------------------------------------------------
# Update FastAPI application CORS setting
# ---------------------------------------------------------------------------

DASHBOARD_ORIGIN="https://${DASHBOARD_FQDN}"

echo
echo "Updating FastAPI allowed dashboard origin..."

az containerapp update \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${API_APP}" \
    --set-env-vars \
        "PEARLS_API_ALLOWED_CORS_ORIGINS=[\"${DASHBOARD_ORIGIN}\"]" \
    --output none


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo
echo "Production dashboard deployed."
echo
echo "Dashboard:"
echo "  https://${DASHBOARD_FQDN}"
echo
echo "FastAPI:"
echo "  https://${API_FQDN}"
echo
echo "Dashboard API base URL:"
echo "  ${API_BASE_URL}"
echo
echo "FastAPI allowed dashboard origin:"
echo "  ${DASHBOARD_ORIGIN}"