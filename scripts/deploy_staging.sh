#!/usr/bin/env bash

set -Eeuo pipefail


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOCATION="${LOCATION:-centralindia}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-pearls-aqi-staging}"
CONTAINER_ENV="${CONTAINER_ENV:-cae-pearls-aqi-staging}"
IDENTITY_NAME="${IDENTITY_NAME:-id-pearls-aqi-staging}"

ACR_NAME="${ACR_NAME:-walpole}"
ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-walpole.azurecr.io}"

API_APP="${API_APP:-ca-pearls-aqi-api-staging}"
DASHBOARD_APP="${DASHBOARD_APP:-ca-pearls-aqi-dashboard-staging}"

STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-}"
STORAGE_CONTAINER="${STORAGE_CONTAINER:-artifacts}"
IMAGE_TAG="${IMAGE_TAG:-}"

MAX_RETRIES="${MAX_RETRIES:-5}"
INITIAL_RETRY_DELAY="${INITIAL_RETRY_DELAY:-10}"
PROVISIONING_TIMEOUT_SECONDS="${
    PROVISIONING_TIMEOUT_SECONDS:-900
}"
PROVISIONING_POLL_SECONDS="${
    PROVISIONING_POLL_SECONDS:-15
}"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

if [[ -z "${IMAGE_TAG}" ]]; then
    echo "IMAGE_TAG is required." >&2
    exit 1
fi

if [[ -z "${STORAGE_ACCOUNT}" ]]; then
    echo "STORAGE_ACCOUNT is required." >&2
    exit 1
fi

API_IMAGE="${
    ACR_LOGIN_SERVER
}/pearls-aqi/api:${IMAGE_TAG}"

DASHBOARD_IMAGE="${
    ACR_LOGIN_SERVER
}/pearls-aqi/dashboard:${IMAGE_TAG}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

retry_command() {
    local attempt=1
    local delay="${INITIAL_RETRY_DELAY}"

    while true; do
        if "$@"; then
            return 0
        fi

        if (( attempt >= MAX_RETRIES )); then
            echo >&2
            echo "Command failed after ${MAX_RETRIES} attempts:" >&2
            printf ' %q' "$@" >&2
            echo >&2
            return 1
        fi

        echo >&2
        echo \
            "Transient Azure command failure. " \
            "Retrying in ${delay} seconds " \
            "(attempt ${attempt}/${MAX_RETRIES})..." \
            >&2

        sleep "${delay}"

        attempt=$((attempt + 1))
        delay=$((delay * 2))
    done
}


container_app_exists() {
    az containerapp show \
        --name "$1" \
        --resource-group "${RESOURCE_GROUP}" \
        --output none \
        >/dev/null 2>&1
}


wait_for_environment() {
    local elapsed=0
    local state=""

    echo \
        "Waiting for Container Apps environment " \
        "${CONTAINER_ENV}..."

    while (( elapsed < PROVISIONING_TIMEOUT_SECONDS )); do
        state="$(
            az containerapp env show \
                --name "${CONTAINER_ENV}" \
                --resource-group "${RESOURCE_GROUP}" \
                --query properties.provisioningState \
                --output tsv \
                2>/dev/null \
                || true
        )"

        case "${state}" in
            Succeeded)
                echo \
                    "Container Apps environment is ready."
                return 0
                ;;

            Failed | Canceled)
                echo \
                    "Container Apps environment entered " \
                    "state: ${state}" \
                    >&2
                return 1
                ;;

            *)
                echo \
                    "Environment state: " \
                    "${state:-not available yet}"
                ;;
        esac

        sleep "${PROVISIONING_POLL_SECONDS}"

        elapsed=$(
            (
                elapsed
                + PROVISIONING_POLL_SECONDS
            )
        )
    done

    echo \
        "Timed out waiting for Container Apps " \
        "environment provisioning." \
        >&2

    return 1
}


wait_for_container_app() {
    local app_name="$1"
    local elapsed=0
    local state=""

    echo \
        "Waiting for Container App ${app_name}..."

    while (( elapsed < PROVISIONING_TIMEOUT_SECONDS )); do
        state="$(
            az containerapp show \
                --name "${app_name}" \
                --resource-group "${RESOURCE_GROUP}" \
                --query properties.provisioningState \
                --output tsv \
                2>/dev/null \
                || true
        )"

        case "${state}" in
            Succeeded)
                echo \
                    "Container App ${app_name} is ready."
                return 0
                ;;

            Failed | Canceled)
                echo \
                    "Container App ${app_name} entered " \
                    "state: ${state}" \
                    >&2
                return 1
                ;;

            *)
                echo \
                    "${app_name} state: " \
                    "${state:-not available yet}"
                ;;
        esac

        sleep "${PROVISIONING_POLL_SECONDS}"

        elapsed=$(
            (
                elapsed
                + PROVISIONING_POLL_SECONDS
            )
        )
    done

    echo \
        "Timed out waiting for Container App " \
        "${app_name}." \
        >&2

    return 1
}


wait_for_fqdn() {
    local app_name="$1"
    local elapsed=0
    local fqdn=""

    while (( elapsed < PROVISIONING_TIMEOUT_SECONDS )); do
        fqdn="$(
            az containerapp show \
                --name "${app_name}" \
                --resource-group "${RESOURCE_GROUP}" \
                --query \
                    properties.configuration.ingress.fqdn \
                --output tsv \
                2>/dev/null \
                || true
        )"

        if [[ -n "${fqdn}" ]]; then
            printf '%s\n' "${fqdn}"
            return 0
        fi

        sleep "${PROVISIONING_POLL_SECONDS}"

        elapsed=$(
            (
                elapsed
                + PROVISIONING_POLL_SECONDS
            )
        )
    done

    echo \
        "Timed out waiting for FQDN for ${app_name}." \
        >&2

    return 1
}


ensure_role_assignment() {
    local principal_id="$1"
    local scope="$2"
    local role="$3"

    local assignment_id=""

    assignment_id="$(
        az role assignment list \
            --assignee-object-id "${principal_id}" \
            --scope "${scope}" \
            --role "${role}" \
            --query "[0].id" \
            --output tsv \
            2>/dev/null \
            || true
    )"

    if [[ -n "${assignment_id}" ]]; then
        echo \
            "Role already assigned: ${role}"
        return 0
    fi

    retry_command \
        az role assignment create \
            --assignee-object-id "${principal_id}" \
            --assignee-principal-type \
                ServicePrincipal \
            --scope "${scope}" \
            --role "${role}" \
            --output none
}


# ---------------------------------------------------------------------------
# Azure account check
# ---------------------------------------------------------------------------

echo "Checking Azure authentication..."

retry_command \
    az account show \
        --output none


# ---------------------------------------------------------------------------
# Resource group
# ---------------------------------------------------------------------------

echo "Ensuring staging resource group..."

retry_command \
    az group create \
        --name "${RESOURCE_GROUP}" \
        --location "${LOCATION}" \
        --tags \
            project=pearls-aqi \
            environment=staging \
            managed-by=azure-cli \
        --output none


# ---------------------------------------------------------------------------
# Managed identity
# ---------------------------------------------------------------------------

echo "Ensuring user-assigned managed identity..."

if ! az identity show \
    --name "${IDENTITY_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --output none \
    >/dev/null 2>&1; then

    retry_command \
        az identity create \
            --name "${IDENTITY_NAME}" \
            --resource-group "${RESOURCE_GROUP}" \
            --location "${LOCATION}" \
            --output none
fi

IDENTITY_ID="$(
    retry_command \
        az identity show \
            --name "${IDENTITY_NAME}" \
            --resource-group "${RESOURCE_GROUP}" \
            --query id \
            --output tsv
)"

IDENTITY_PRINCIPAL_ID="$(
    retry_command \
        az identity show \
            --name "${IDENTITY_NAME}" \
            --resource-group "${RESOURCE_GROUP}" \
            --query principalId \
            --output tsv
)"


# ---------------------------------------------------------------------------
# ACR access
# ---------------------------------------------------------------------------

ACR_ID="$(
    retry_command \
        az acr show \
            --name "${ACR_NAME}" \
            --query id \
            --output tsv
)"

echo "Ensuring ACR pull permission..."

ensure_role_assignment \
    "${IDENTITY_PRINCIPAL_ID}" \
    "${ACR_ID}" \
    "AcrPull"


# ---------------------------------------------------------------------------
# Container Apps environment
# ---------------------------------------------------------------------------

echo "Ensuring Container Apps environment..."

if ! az containerapp env show \
    --name "${CONTAINER_ENV}" \
    --resource-group "${RESOURCE_GROUP}" \
    --output none \
    >/dev/null 2>&1; then

    retry_command \
        az containerapp env create \
            --name "${CONTAINER_ENV}" \
            --resource-group "${RESOURCE_GROUP}" \
            --location "${LOCATION}" \
            --logs-destination none \
            --no-wait \
            --output none
fi

wait_for_environment


# ---------------------------------------------------------------------------
# Storage account
# ---------------------------------------------------------------------------

echo "Ensuring storage account..."

if ! az storage account show \
    --name "${STORAGE_ACCOUNT}" \
    --resource-group "${RESOURCE_GROUP}" \
    --output none \
    >/dev/null 2>&1; then

    retry_command \
        az storage account create \
            --name "${STORAGE_ACCOUNT}" \
            --resource-group "${RESOURCE_GROUP}" \
            --location "${LOCATION}" \
            --sku Standard_LRS \
            --kind StorageV2 \
            --allow-blob-public-access false \
            --min-tls-version TLS1_2 \
            --output none
fi

STORAGE_ID="$(
    retry_command \
        az storage account show \
            --name "${STORAGE_ACCOUNT}" \
            --resource-group "${RESOURCE_GROUP}" \
            --query id \
            --output tsv
)"

echo "Ensuring Blob Storage permission..."

ensure_role_assignment \
    "${IDENTITY_PRINCIPAL_ID}" \
    "${STORAGE_ID}" \
    "Storage Blob Data Contributor"


# ---------------------------------------------------------------------------
# Blob container
# ---------------------------------------------------------------------------

echo "Ensuring Blob container..."

retry_command \
    az storage container create \
        --name "${STORAGE_CONTAINER}" \
        --account-name "${STORAGE_ACCOUNT}" \
        --auth-mode login \
        --public-access off \
        --output none


# ---------------------------------------------------------------------------
# FastAPI Container App
# ---------------------------------------------------------------------------

echo "Deploying FastAPI staging application..."

if container_app_exists "${API_APP}"; then
    retry_command \
        az containerapp update \
            --name "${API_APP}" \
            --resource-group "${RESOURCE_GROUP}" \
            --image "${API_IMAGE}" \
            --set-env-vars \
                PEARLS_API_ENVIRONMENT=staging \
                PEARLS_API_LOG_LEVEL=INFO \
                PEARLS_API_PHASE_6_LATEST_DIRECTORY=/app/aqi/latest \
                PEARLS_API_ARTIFACT_CACHE_SECONDS=60 \
                PEARLS_API_FORECAST_AGING_THRESHOLD_HOURS=48 \
                PEARLS_API_FORECAST_STALENESS_THRESHOLD_HOURS=168 \
            --no-wait \
            --output none
else
    if ! retry_command \
        az containerapp create \
            --name "${API_APP}" \
            --resource-group "${RESOURCE_GROUP}" \
            --environment "${CONTAINER_ENV}" \
            --image "${API_IMAGE}" \
            --user-assigned "${IDENTITY_ID}" \
            --registry-server "${ACR_LOGIN_SERVER}" \
            --registry-identity "${IDENTITY_ID}" \
            --ingress external \
            --target-port 8000 \
            --transport auto \
            --cpu 0.25 \
            --memory 0.5Gi \
            --min-replicas 0 \
            --max-replicas 1 \
            --env-vars \
                PEARLS_API_ENVIRONMENT=staging \
                PEARLS_API_LOG_LEVEL=INFO \
                PEARLS_API_PHASE_6_LATEST_DIRECTORY=/app/aqi/latest \
                PEARLS_API_ARTIFACT_CACHE_SECONDS=60 \
                PEARLS_API_FORECAST_AGING_THRESHOLD_HOURS=48 \
                PEARLS_API_FORECAST_STALENESS_THRESHOLD_HOURS=168 \
            --no-wait \
            --output none; then

        # The Azure request may have succeeded even if the
        # local CLI connection was interrupted.
        if ! container_app_exists "${API_APP}"; then
            echo \
                "FastAPI Container App was not created." \
                >&2
            exit 1
        fi
    fi
fi

wait_for_container_app "${API_APP}"

API_FQDN="$(
    wait_for_fqdn "${API_APP}"
)"

API_BASE_URL="https://${API_FQDN}/api/v1"


# ---------------------------------------------------------------------------
# Streamlit Container App
# ---------------------------------------------------------------------------

echo "Deploying Streamlit staging application..."

if container_app_exists "${DASHBOARD_APP}"; then
    retry_command \
        az containerapp update \
            --name "${DASHBOARD_APP}" \
            --resource-group "${RESOURCE_GROUP}" \
            --image "${DASHBOARD_IMAGE}" \
            --set-env-vars \
                FASTAPI_BASE_URL="${API_BASE_URL}" \
                DASHBOARD_ENVIRONMENT=staging \
            --no-wait \
            --output none
else
    if ! retry_command \
        az containerapp create \
            --name "${DASHBOARD_APP}" \
            --resource-group "${RESOURCE_GROUP}" \
            --environment "${CONTAINER_ENV}" \
            --image "${DASHBOARD_IMAGE}" \
            --user-assigned "${IDENTITY_ID}" \
            --registry-server "${ACR_LOGIN_SERVER}" \
            --registry-identity "${IDENTITY_ID}" \
            --ingress external \
            --target-port 8501 \
            --transport auto \
            --cpu 0.25 \
            --memory 0.5Gi \
            --min-replicas 0 \
            --max-replicas 1 \
            --env-vars \
                FASTAPI_BASE_URL="${API_BASE_URL}" \
                DASHBOARD_ENVIRONMENT=staging \
            --no-wait \
            --output none; then

        # The remote creation may have succeeded even if
        # the Azure CLI connection was reset.
        if ! container_app_exists "${DASHBOARD_APP}"; then
            echo \
                "Streamlit Container App was not created." \
                >&2
            exit 1
        fi
    fi
fi

wait_for_container_app "${DASHBOARD_APP}"

DASHBOARD_FQDN="$(
    wait_for_fqdn "${DASHBOARD_APP}"
)"


# ---------------------------------------------------------------------------
# Final resource summary
# ---------------------------------------------------------------------------

echo
echo "Staging deployment completed."
echo "Resource group: ${RESOURCE_GROUP}"
echo "Environment:    ${CONTAINER_ENV}"
echo "Identity:       ${IDENTITY_NAME}"
echo "Storage:        ${STORAGE_ACCOUNT}"
echo "Blob container: ${STORAGE_CONTAINER}"
echo
echo "API:       https://${API_FQDN}"
echo "API docs:  https://${API_FQDN}/docs"
echo "Dashboard: https://${DASHBOARD_FQDN}"