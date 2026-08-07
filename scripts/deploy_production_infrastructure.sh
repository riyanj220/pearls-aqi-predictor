#!/usr/bin/env bash

set -Eeuo pipefail


# ---------------------------------------------------------------------------
# Production infrastructure configuration
# ---------------------------------------------------------------------------

LOCATION="${LOCATION:-centralindia}"

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-pearls-aqi-prod}"

# The Azure for Students subscription currently allows only one
# Container Apps environment, so production reuses staging's environment.
CONTAINER_ENV="${CONTAINER_ENV:-cae-pearls-aqi-staging}"

CONTAINER_ENV_RESOURCE_GROUP="${CONTAINER_ENV_RESOURCE_GROUP:-rg-pearls-aqi-staging}"

IDENTITY_NAME="${IDENTITY_NAME:-id-pearls-aqi-prod}"

ACR_NAME="${ACR_NAME:-walpole}"

STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-stpearlsaqiriyan}"

STORAGE_RESOURCE_GROUP="${STORAGE_RESOURCE_GROUP:-rg-pearls-aqi-staging}"

STORAGE_CONTAINER="${STORAGE_CONTAINER:-artifacts-prod}"

MAX_RETRIES="${MAX_RETRIES:-5}"

INITIAL_RETRY_DELAY="${INITIAL_RETRY_DELAY:-10}"

PROVISIONING_TIMEOUT_SECONDS="${PROVISIONING_TIMEOUT_SECONDS:-900}"

PROVISIONING_POLL_SECONDS="${PROVISIONING_POLL_SECONDS:-15}"


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
            echo \
                "Command failed after " \
                "${MAX_RETRIES} attempts:" \
                >&2

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


resource_group_exists() {
    az group show \
        --name "${RESOURCE_GROUP}" \
        --output none \
        >/dev/null 2>&1
}


environment_exists() {
    az containerapp env show \
        --name "${CONTAINER_ENV}" \
        --resource-group "${CONTAINER_ENV_RESOURCE_GROUP}" \
        --output none \
        >/dev/null 2>&1
}


identity_exists() {
    az identity show \
        --name "${IDENTITY_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --output none \
        >/dev/null 2>&1
}


wait_for_environment() {
    local elapsed=0
    local state=""

    echo \
        "Waiting for Container Apps environment ${CONTAINER_ENV}..."

    while (( elapsed < PROVISIONING_TIMEOUT_SECONDS )); do
        state="$(
            az containerapp env show \
                --name "${CONTAINER_ENV}" \
                --resource-group "${CONTAINER_ENV_RESOURCE_GROUP}" \
                --query properties.provisioningState \
                --output tsv \
                2>/dev/null \
                || true
        )"

        case "${state}" in
            Succeeded)
                echo "Container Apps environment is ready."
                return 0
                ;;

            Failed|Canceled)
                echo \
                    "Container Apps environment entered state: ${state}" \
                    >&2
                return 1
                ;;

            *)
                echo \
                    "Environment state: ${state:-not available yet}"
                ;;
        esac

        sleep "${PROVISIONING_POLL_SECONDS}"

        elapsed=$((elapsed + PROVISIONING_POLL_SECONDS))
    done

    echo \
        "Timed out waiting for Container Apps environment." \
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

    echo \
        "Assigning role: ${role}"

    retry_command \
        az role assignment create \
            --assignee-object-id "${principal_id}" \
            --assignee-principal-type ServicePrincipal \
            --scope "${scope}" \
            --role "${role}" \
            --output none
}


# ---------------------------------------------------------------------------
# Azure authentication
# ---------------------------------------------------------------------------

echo "Checking Azure authentication..."

retry_command \
    az account show \
        --output none


SUBSCRIPTION_ID="$(
    az account show \
        --query id \
        --output tsv
)"


# ---------------------------------------------------------------------------
# Production resource group
# ---------------------------------------------------------------------------

echo
echo "Ensuring production resource group..."

if ! resource_group_exists; then
    retry_command \
        az group create \
            --name "${RESOURCE_GROUP}" \
            --location "${LOCATION}" \
            --tags \
                project=pearls-aqi \
                environment=production \
                managed-by=azure-cli \
            --output none
else
    echo \
        "Production resource group already exists."
fi


RESOURCE_GROUP_ID="$(
    az group show \
        --name "${RESOURCE_GROUP}" \
        --query id \
        --output tsv
)"


# ---------------------------------------------------------------------------
# Production managed identity
# ---------------------------------------------------------------------------

echo
echo "Ensuring production managed identity..."

if ! identity_exists; then
    retry_command \
        az identity create \
            --name "${IDENTITY_NAME}" \
            --resource-group "${RESOURCE_GROUP}" \
            --location "${LOCATION}" \
            --tags \
                project=pearls-aqi \
                environment=production \
            --output none
else
    echo \
        "Production managed identity already exists."
fi


IDENTITY_ID="$(
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


# ---------------------------------------------------------------------------
# Shared ACR access
# ---------------------------------------------------------------------------

echo
echo "Resolving shared Azure Container Registry..."

ACR_ID="$(
    az acr show \
        --name "${ACR_NAME}" \
        --query id \
        --output tsv
)"


ACR_LOGIN_SERVER="$(
    az acr show \
        --name "${ACR_NAME}" \
        --query loginServer \
        --output tsv
)"


echo "Ensuring AcrPull permission..."

ensure_role_assignment \
    "${IDENTITY_PRINCIPAL_ID}" \
    "${ACR_ID}" \
    "AcrPull"


# ---------------------------------------------------------------------------
# Production Container Apps environment
# ---------------------------------------------------------------------------

echo
echo "Resolving shared Container Apps environment..."

if ! environment_exists; then
    echo \
        "Required shared Container Apps environment was not found:" \
        >&2

    echo \
        "${CONTAINER_ENV_RESOURCE_GROUP}/${CONTAINER_ENV}" \
        >&2

    exit 1
fi

echo \
    "Reusing shared Container Apps environment: ${CONTAINER_ENV}"


wait_for_environment


CONTAINER_ENV_ID="$(
    az containerapp env show \
        --name "${CONTAINER_ENV}" \
        --resource-group "${CONTAINER_ENV_RESOURCE_GROUP}" \
        --query id \
        --output tsv
)"


# ---------------------------------------------------------------------------
# Shared storage account
# ---------------------------------------------------------------------------

echo
echo "Resolving shared storage account..."

STORAGE_ID="$(
    az storage account show \
        --name "${STORAGE_ACCOUNT}" \
        --resource-group "${STORAGE_RESOURCE_GROUP}" \
        --query id \
        --output tsv
)"


# ---------------------------------------------------------------------------
# Production Blob container
# ---------------------------------------------------------------------------

echo
echo "Ensuring isolated production Blob container..."

CONTAINER_EXISTS="$(
    az storage container exists \
        --name "${STORAGE_CONTAINER}" \
        --account-name "${STORAGE_ACCOUNT}" \
        --auth-mode login \
        --query exists \
        --output tsv
)"

if [[ "${CONTAINER_EXISTS}" != "true" ]]; then
    retry_command \
        az storage container create \
            --name "${STORAGE_CONTAINER}" \
            --account-name "${STORAGE_ACCOUNT}" \
            --auth-mode login \
            --output none

    echo \
        "Production Blob container created."
else
    echo \
        "Production Blob container already exists."
fi


# ---------------------------------------------------------------------------
# Storage data access
# ---------------------------------------------------------------------------

echo
echo "Ensuring production Blob data permission..."

ensure_role_assignment \
    "${IDENTITY_PRINCIPAL_ID}" \
    "${STORAGE_ID}" \
    "Storage Blob Data Contributor"


# ---------------------------------------------------------------------------
# Production Resource Manager read access
# ---------------------------------------------------------------------------

echo
echo "Ensuring production Resource Manager read permission..."

ensure_role_assignment \
    "${IDENTITY_PRINCIPAL_ID}" \
    "${RESOURCE_GROUP_ID}" \
    "Reader"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo
echo "Production infrastructure ready."
echo
echo "Subscription:          ${SUBSCRIPTION_ID}"
echo "Resource group:        ${RESOURCE_GROUP}"
echo "Location:              ${LOCATION}"
echo "Container environment: ${CONTAINER_ENV}"
echo "Managed identity:      ${IDENTITY_NAME}"
echo "Identity client ID:    ${IDENTITY_CLIENT_ID}"
echo "ACR:                    ${ACR_LOGIN_SERVER}"
echo "Storage account:       ${STORAGE_ACCOUNT}"
echo "Production container:  ${STORAGE_CONTAINER}"
echo
echo "No Container Apps or scheduled jobs were deployed."