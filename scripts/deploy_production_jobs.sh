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

AZURE_RETRY_ATTEMPTS="${AZURE_RETRY_ATTEMPTS:-5}"
AZURE_RETRY_DELAY_SECONDS="${AZURE_RETRY_DELAY_SECONDS:-10}"

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
        echo "Missing required variable: ${variable_name}" >&2
        exit 1
    fi
done


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

retry_command() {
    local attempt=1

    while (( attempt <= AZURE_RETRY_ATTEMPTS )); do
        if "$@"; then
            return 0
        fi

        if (( attempt == AZURE_RETRY_ATTEMPTS )); then
            echo "Command failed after ${AZURE_RETRY_ATTEMPTS} attempts:" >&2
            printf '  %q' "$@" >&2
            echo >&2
            return 1
        fi

        echo \
            "Azure command failed on attempt ${attempt}/${AZURE_RETRY_ATTEMPTS}; " \
            "retrying in ${AZURE_RETRY_DELAY_SECONDS}s..." \
            >&2

        sleep "${AZURE_RETRY_DELAY_SECONDS}"
        attempt=$((attempt + 1))
    done
}


source_value() {
    local job_name="$1"
    local query="$2"

    retry_command \
        az containerapp job show \
        --resource-group "${SOURCE_RESOURCE_GROUP}" \
        --name "${job_name}" \
        --query "${query}" \
        --output tsv
}


job_exists() {
    local job_name="$1"

    az containerapp job show \
        --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
        --name "${job_name}" \
        --output none \
        >/dev/null 2>&1
}


delete_existing_job() {
    local job_name="$1"

    if job_exists "${job_name}"; then
        echo "Deleting existing ${job_name}..."

        retry_command \
            az containerapp job delete \
            --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
            --name "${job_name}" \
            --yes \
            --output none
    fi
}


deploy_job_from_yaml() {
    local job_name="$1"
    local yaml_file="$2"
    local attempt=1
    local state=""

    while (( attempt <= AZURE_RETRY_ATTEMPTS )); do
        echo \
            "Deploying ${job_name} " \
            "(attempt ${attempt}/${AZURE_RETRY_ATTEMPTS})..."

        if az containerapp job create \
            --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
            --name "${job_name}" \
            --yaml "${yaml_file}" \
            --output none
        then
            return 0
        fi

        # A connection reset can happen after Azure accepts the request.
        # Check whether the resource was created before retrying.
        state="$(
            az containerapp job show \
                --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
                --name "${job_name}" \
                --query properties.provisioningState \
                --output tsv \
                2>/dev/null \
                || true
        )"

        if [[ "${state}" == "Succeeded" ]]; then
            echo \
                "${job_name} exists and provisioning succeeded " \
                "despite the client-side error."
            return 0
        fi

        if (( attempt == AZURE_RETRY_ATTEMPTS )); then
            echo \
                "Failed to deploy ${job_name} after " \
                "${AZURE_RETRY_ATTEMPTS} attempts." \
                >&2
            return 1
        fi

        if job_exists "${job_name}"; then
            echo \
                "${job_name} exists in state '${state:-unknown}'. " \
                "Deleting it before retry..."

            retry_command \
                az containerapp job delete \
                --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
                --name "${job_name}" \
                --yes \
                --output none
        fi

        sleep "${AZURE_RETRY_DELAY_SECONDS}"
        attempt=$((attempt + 1))
    done
}


validate_deployed_job() {
    local job_name="$1"

    retry_command \
        az containerapp job show \
        --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
        --name "${job_name}" \
        --query '{
            name:name,
            state:properties.provisioningState,
            environmentId:properties.environmentId,
            image:properties.template.containers[0].image
        }' \
        --output json
}


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

echo "Validating production scheduled-job deployment..."

retry_command \
    az account show \
    --output none

# This file may intentionally be modified locally as a deployment-only
# workaround. RELEASE_SHA still pins the immutable Docker image, so local
# uncommitted script changes are not included in the deployed image.
if [[ -n "$(git status --porcelain)" ]]; then
    echo
    echo "WARNING: Working tree is not clean."
    echo "Only this already-built immutable image will be deployed:"
    echo "  ${PIPELINE_IMAGE}"
    echo "Uncommitted local files are NOT inside that image."
    echo
fi

if ! retry_command \
    az acr repository show \
    --name "${ACR_NAME}" \
    --image "pearls-aqi/pipeline:${RELEASE_SHA}" \
    --output none
then
    echo "Production pipeline image does not exist: ${PIPELINE_IMAGE}" >&2
    exit 1
fi


# ---------------------------------------------------------------------------
# Resolve Azure infrastructure
# ---------------------------------------------------------------------------

ENVIRONMENT_RESOURCE_ID="$(
    retry_command \
        az containerapp env show \
        --resource-group "${ENVIRONMENT_RESOURCE_GROUP}" \
        --name "${ENVIRONMENT_NAME}" \
        --query id \
        --output tsv
)"

IDENTITY_RESOURCE_ID="$(
    retry_command \
        az identity show \
        --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
        --name "${IDENTITY_NAME}" \
        --query id \
        --output tsv
)"

IDENTITY_CLIENT_ID="$(
    retry_command \
        az identity show \
        --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
        --name "${IDENTITY_NAME}" \
        --query clientId \
        --output tsv
)"

SUBSCRIPTION_ID="$(
    retry_command \
        az account show \
        --query id \
        --output tsv
)"

ENVIRONMENT_STATE="$(
    retry_command \
        az containerapp env show \
        --resource-group "${ENVIRONMENT_RESOURCE_GROUP}" \
        --name "${ENVIRONMENT_NAME}" \
        --query properties.provisioningState \
        --output tsv
)"

if [[ "${ENVIRONMENT_STATE}" != "Succeeded" ]]; then
    echo \
        "Shared Container Apps environment is not ready: ${ENVIRONMENT_STATE}" \
        >&2
    exit 1
fi


echo
echo "Using shared Container Apps environment:"
echo "  ${ENVIRONMENT_RESOURCE_ID}"
echo
echo "Using immutable pipeline image:"
echo "  ${PIPELINE_IMAGE}"


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
echo "Features:   ${FEATURE_CPU} CPU / ${FEATURE_MEMORY}"
echo "Forecast:   ${FORECAST_CPU} CPU / ${FORECAST_MEMORY}"
echo "Retraining: ${RETRAINING_CPU} CPU / ${RETRAINING_MEMORY}"
echo "Monitoring: ${MONITORING_CPU} CPU / ${MONITORING_MEMORY}"


# ---------------------------------------------------------------------------
# Temporary YAML files
# ---------------------------------------------------------------------------

JOB_YAML_DIR="$(mktemp -d)"
chmod 700 "${JOB_YAML_DIR}"

cleanup() {
    rm -rf "${JOB_YAML_DIR}"
}

trap cleanup EXIT


# ---------------------------------------------------------------------------
# Hourly features YAML
# ---------------------------------------------------------------------------

FEATURE_YAML="${JOB_YAML_DIR}/features.yaml"

cat >"${FEATURE_YAML}" <<EOF_YAML
identity:
  type: UserAssigned
  userAssignedIdentities:
    "${IDENTITY_RESOURCE_ID}": {}

properties:
  environmentId: "${ENVIRONMENT_RESOURCE_ID}"

  configuration:
    triggerType: Schedule
    replicaTimeout: 900
    replicaRetryLimit: 1

    scheduleTriggerConfig:
      cronExpression: "15 * * * *"
      parallelism: 1
      replicaCompletionCount: 1

    registries:
      - server: "${ACR_SERVER}"
        identity: "${IDENTITY_RESOURCE_ID}"

    secrets:
      - name: openaq-api-key
        value: "${OPENAQ_API_KEY}"
      - name: hopsworks-api-key
        value: "${HOPSWORKS_API_KEY}"

  template:
    containers:
      - name: hourly-features
        image: "${PIPELINE_IMAGE}"
        command:
          - "/app/bin/run_hourly_features"
        resources:
          cpu: ${FEATURE_CPU}
          memory: "${FEATURE_MEMORY}"
        env:
          - name: APP_ENV
            value: production
          - name: SERVICE_ROLE
            value: hourly_features
          - name: AZURE_CLIENT_ID
            value: "${IDENTITY_CLIENT_ID}"
          - name: FEATURE_STORE_BACKEND
            value: hopsworks
          - name: MODEL_REGISTRY_BACKEND
            value: hopsworks
          - name: MLOPS_DRY_RUN
            value: "false"
          - name: OPENAQ_API_KEY
            secretRef: openaq-api-key
          - name: HOPSWORKS_API_KEY
            secretRef: hopsworks-api-key
          - name: HOPSWORKS_PROJECT
            value: "${HOPSWORKS_PROJECT}"
          - name: HOPSWORKS_HOST
            value: "${HOPSWORKS_HOST}"

tags:
  project: pearls-aqi
  environment: production
  workload: hourly-features
  release: "${RELEASE_SHA}"
EOF_YAML


# ---------------------------------------------------------------------------
# Forecast YAML
# ---------------------------------------------------------------------------

FORECAST_YAML="${JOB_YAML_DIR}/forecast.yaml"

cat >"${FORECAST_YAML}" <<EOF_YAML
identity:
  type: UserAssigned
  userAssignedIdentities:
    "${IDENTITY_RESOURCE_ID}": {}

properties:
  environmentId: "${ENVIRONMENT_RESOURCE_ID}"

  configuration:
    triggerType: Schedule
    replicaTimeout: 1800
    replicaRetryLimit: 1

    scheduleTriggerConfig:
      cronExpression: "0 */6 * * *"
      parallelism: 1
      replicaCompletionCount: 1

    registries:
      - server: "${ACR_SERVER}"
        identity: "${IDENTITY_RESOURCE_ID}"

    secrets:
      - name: openaq-api-key
        value: "${OPENAQ_API_KEY}"
      - name: hopsworks-api-key
        value: "${HOPSWORKS_API_KEY}"

  template:
    containers:
      - name: forecast-publication
        image: "${PIPELINE_IMAGE}"
        resources:
          cpu: ${FORECAST_CPU}
          memory: "${FORECAST_MEMORY}"
        env:
          - name: APP_ENV
            value: production
          - name: SERVICE_ROLE
            value: forecast
          - name: AZURE_CLIENT_ID
            value: "${IDENTITY_CLIENT_ID}"
          - name: ARTIFACT_BACKEND
            value: azure_blob
          - name: AZURE_STORAGE_ACCOUNT
            value: "${STORAGE_ACCOUNT}"
          - name: AZURE_STORAGE_CONTAINER
            value: "${STORAGE_CONTAINER}"
          - name: FEATURE_STORE_BACKEND
            value: hopsworks
          - name: MODEL_REGISTRY_BACKEND
            value: hopsworks
          - name: MLOPS_DRY_RUN
            value: "false"
          - name: OPENAQ_API_KEY
            secretRef: openaq-api-key
          - name: HOPSWORKS_API_KEY
            secretRef: hopsworks-api-key
          - name: HOPSWORKS_PROJECT
            value: "${HOPSWORKS_PROJECT}"
          - name: HOPSWORKS_HOST
            value: "${HOPSWORKS_HOST}"

tags:
  project: pearls-aqi
  environment: production
  workload: forecast-publication
  release: "${RELEASE_SHA}"
EOF_YAML


# ---------------------------------------------------------------------------
# Retraining YAML
# ---------------------------------------------------------------------------

RETRAINING_YAML="${JOB_YAML_DIR}/retraining.yaml"

cat >"${RETRAINING_YAML}" <<EOF_YAML
identity:
  type: UserAssigned
  userAssignedIdentities:
    "${IDENTITY_RESOURCE_ID}": {}

properties:
  environmentId: "${ENVIRONMENT_RESOURCE_ID}"

  configuration:
    triggerType: Schedule
    replicaTimeout: 3600
    replicaRetryLimit: 1

    scheduleTriggerConfig:
      cronExpression: "30 3 * * *"
      parallelism: 1
      replicaCompletionCount: 1

    registries:
      - server: "${ACR_SERVER}"
        identity: "${IDENTITY_RESOURCE_ID}"

    secrets:
      - name: hopsworks-api-key
        value: "${HOPSWORKS_API_KEY}"

  template:
    containers:
      - name: daily-retraining
        image: "${PIPELINE_IMAGE}"
        command:
          - "/app/bin/run_daily_retraining"
        resources:
          cpu: ${RETRAINING_CPU}
          memory: "${RETRAINING_MEMORY}"
        env:
          - name: APP_ENV
            value: production
          - name: SERVICE_ROLE
            value: retraining
          - name: AZURE_CLIENT_ID
            value: "${IDENTITY_CLIENT_ID}"
          - name: ARTIFACT_BACKEND
            value: azure_blob
          - name: AZURE_STORAGE_ACCOUNT
            value: "${STORAGE_ACCOUNT}"
          - name: AZURE_STORAGE_CONTAINER
            value: "${STORAGE_CONTAINER}"
          - name: FEATURE_STORE_BACKEND
            value: hopsworks
          - name: MODEL_REGISTRY_BACKEND
            value: hopsworks
          - name: MLOPS_DRY_RUN
            value: "false"
          - name: HOPSWORKS_API_KEY
            secretRef: hopsworks-api-key
          - name: HOPSWORKS_PROJECT
            value: "${HOPSWORKS_PROJECT}"
          - name: HOPSWORKS_HOST
            value: "${HOPSWORKS_HOST}"

tags:
  project: pearls-aqi
  environment: production
  workload: daily-retraining
  release: "${RELEASE_SHA}"
EOF_YAML


# ---------------------------------------------------------------------------
# Monitoring YAML
# ---------------------------------------------------------------------------

MONITORING_YAML="${JOB_YAML_DIR}/monitoring.yaml"

WEBHOOK_SECRET_BLOCK=""
WEBHOOK_ENV_BLOCK=""
WEBHOOK_TOKEN_SECRET_BLOCK=""
WEBHOOK_TOKEN_ENV_BLOCK=""

if [[ -n "${PRODUCTION_HEALTH_WEBHOOK_URL:-}" ]]; then
    WEBHOOK_ENABLED="true"

    WEBHOOK_SECRET_BLOCK="$(cat <<EOF_BLOCK
      - name: production-health-webhook-url
        value: "${PRODUCTION_HEALTH_WEBHOOK_URL}"
EOF_BLOCK
)"

    WEBHOOK_ENV_BLOCK="$(cat <<EOF_BLOCK
          - name: PRODUCTION_HEALTH_WEBHOOK_URL
            secretRef: production-health-webhook-url
EOF_BLOCK
)"
else
    WEBHOOK_ENABLED="false"
fi

if [[ -n "${PRODUCTION_HEALTH_WEBHOOK_URL:-}" ]] \
    && [[ -n "${PRODUCTION_HEALTH_WEBHOOK_BEARER_TOKEN:-}" ]]
then
    WEBHOOK_TOKEN_SECRET_BLOCK="$(cat <<EOF_BLOCK
      - name: production-health-webhook-token
        value: "${PRODUCTION_HEALTH_WEBHOOK_BEARER_TOKEN}"
EOF_BLOCK
)"

    WEBHOOK_TOKEN_ENV_BLOCK="$(cat <<EOF_BLOCK
          - name: PRODUCTION_HEALTH_WEBHOOK_BEARER_TOKEN
            secretRef: production-health-webhook-token
EOF_BLOCK
)"
fi

cat >"${MONITORING_YAML}" <<EOF_YAML
identity:
  type: UserAssigned
  userAssignedIdentities:
    "${IDENTITY_RESOURCE_ID}": {}

properties:
  environmentId: "${ENVIRONMENT_RESOURCE_ID}"

  configuration:
    triggerType: Schedule
    replicaTimeout: 600
    replicaRetryLimit: 1

    scheduleTriggerConfig:
      cronExpression: "45 * * * *"
      parallelism: 1
      replicaCompletionCount: 1

    registries:
      - server: "${ACR_SERVER}"
        identity: "${IDENTITY_RESOURCE_ID}"

    secrets:
      - name: hopsworks-api-key
        value: "${HOPSWORKS_API_KEY}"
${WEBHOOK_SECRET_BLOCK}
${WEBHOOK_TOKEN_SECRET_BLOCK}

  template:
    containers:
      - name: production-monitor
        image: "${PIPELINE_IMAGE}"
        command:
          - "/app/bin/run_production_health"
        resources:
          cpu: ${MONITORING_CPU}
          memory: "${MONITORING_MEMORY}"
        env:
          - name: APP_ENV
            value: production
          - name: SERVICE_ROLE
            value: monitoring
          - name: AZURE_CLIENT_ID
            value: "${IDENTITY_CLIENT_ID}"
          - name: PRODUCTION_RESOURCE_GROUP
            value: "${PRODUCTION_RESOURCE_GROUP}"
          - name: FEATURE_JOB_NAME
            value: "${FEATURE_JOB}"
          - name: FORECAST_JOB_NAME
            value: "${FORECAST_JOB}"
          - name: RETRAINING_JOB_NAME
            value: "${RETRAINING_JOB}"
          - name: AZURE_SUBSCRIPTION_ID
            value: "${SUBSCRIPTION_ID}"
          - name: AZURE_JOB_QUERY_BACKEND
            value: arm
          - name: FEATURE_STORE_BACKEND
            value: hopsworks
          - name: MODEL_REGISTRY_BACKEND
            value: hopsworks
          - name: MLOPS_DRY_RUN
            value: "false"
          - name: HOPSWORKS_API_KEY
            secretRef: hopsworks-api-key
          - name: HOPSWORKS_PROJECT
            value: "${HOPSWORKS_PROJECT}"
          - name: HOPSWORKS_HOST
            value: "${HOPSWORKS_HOST}"
          - name: ARTIFACT_BACKEND
            value: azure_blob
          - name: AZURE_STORAGE_ACCOUNT
            value: "${STORAGE_ACCOUNT}"
          - name: AZURE_STORAGE_CONTAINER
            value: "${STORAGE_CONTAINER}"
          - name: PRODUCTION_HEALTH_WEBHOOK_ENABLED
            value: "${WEBHOOK_ENABLED}"
          - name: PRODUCTION_HEALTH_WEBHOOK_TIMEOUT_SECONDS
            value: "15"
${WEBHOOK_ENV_BLOCK}
${WEBHOOK_TOKEN_ENV_BLOCK}

tags:
  project: pearls-aqi
  environment: production
  workload: production-monitoring
  release: "${RELEASE_SHA}"
EOF_YAML

# These temporary files contain secret values.
chmod 600 \
    "${FEATURE_YAML}" \
    "${FORECAST_YAML}" \
    "${RETRAINING_YAML}" \
    "${MONITORING_YAML}"


# ---------------------------------------------------------------------------
# Deploy jobs
# ---------------------------------------------------------------------------

echo
echo "Creating production hourly feature job..."
delete_existing_job "${FEATURE_JOB}"
deploy_job_from_yaml "${FEATURE_JOB}" "${FEATURE_YAML}"


echo
echo "Creating production forecast job..."
delete_existing_job "${FORECAST_JOB}"
deploy_job_from_yaml "${FORECAST_JOB}" "${FORECAST_YAML}"


echo
echo "Creating production daily retraining job..."
delete_existing_job "${RETRAINING_JOB}"
deploy_job_from_yaml "${RETRAINING_JOB}" "${RETRAINING_YAML}"


echo
echo "Creating production monitoring job..."
delete_existing_job "${MONITORING_JOB}"
deploy_job_from_yaml "${MONITORING_JOB}" "${MONITORING_YAML}"


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

echo
echo "Validating deployed production jobs..."

validate_deployed_job "${FEATURE_JOB}"
validate_deployed_job "${FORECAST_JOB}"
validate_deployed_job "${RETRAINING_JOB}"
validate_deployed_job "${MONITORING_JOB}"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo
echo "Production scheduled jobs deployed."
echo
echo "Image:"
echo "  ${PIPELINE_IMAGE}"
echo
echo "Shared Container Apps environment:"
echo "  ${ENVIRONMENT_RESOURCE_ID}"
echo
echo "Jobs:"
echo "  ${FEATURE_JOB}"
echo "  ${FORECAST_JOB}"
echo "  ${RETRAINING_JOB}"
echo "  ${MONITORING_JOB}"
echo
echo "Artifact container:"
echo "  ${STORAGE_CONTAINER}"
echo
echo "Webhook enabled:"
echo "  ${WEBHOOK_ENABLED}"
