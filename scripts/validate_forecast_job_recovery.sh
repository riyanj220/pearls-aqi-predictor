#!/usr/bin/env bash

set -Eeuo pipefail


PROJECT_ROOT="$(
    cd "$(dirname "${BASH_SOURCE[0]}")/.."
    pwd
)"

REPORT_DIRECTORY="${PROJECT_ROOT}/reports/phase_10"
REPORT_PATH="${REPORT_DIRECTORY}/forecast_job_recovery_report.json"

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-pearls-aqi-staging}"
CONTAINER_ENVIRONMENT="${CONTAINER_ENVIRONMENT:-cae-pearls-aqi-staging}"

IDENTITY_NAME="${IDENTITY_NAME:-id-pearls-aqi-staging}"

FORECAST_JOB="${FORECAST_JOB:-job-pearls-aqi-forecast}"
FAILURE_JOB="${FAILURE_JOB:-job-pearls-aqi-failure-test}"

API_APP="${API_APP:-ca-pearls-aqi-api-staging}"

ACR_NAME="${ACR_NAME:-walpole}"
ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-walpole.azurecr.io}"

STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-stpearlsaqiriyan}"
STORAGE_CONTAINER="${STORAGE_CONTAINER:-artifacts}"

EXECUTION_TIMEOUT_SECONDS="${EXECUTION_TIMEOUT_SECONDS:-1800}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-15}"

mkdir -p "${REPORT_DIRECTORY}"

TEMP_DIRECTORY="$(
    mktemp -d
)"

BEFORE_POINTER_PATH="${TEMP_DIRECTORY}/pointer-before.json"
AFTER_FAILURE_POINTER_PATH="${TEMP_DIRECTORY}/pointer-after-failure.json"
AFTER_RECOVERY_POINTER_PATH="${TEMP_DIRECTORY}/pointer-after-recovery.json"

API_AFTER_FAILURE_PATH="${TEMP_DIRECTORY}/api-after-failure.json"
API_AFTER_RECOVERY_PATH="${TEMP_DIRECTORY}/api-after-recovery.json"

FAILURE_EXECUTION_NAME=""
RECOVERY_EXECUTION_NAME=""

cleanup() {
    echo "Cleaning up temporary failure-test job."

    az containerapp job delete \
        --name "${FAILURE_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --yes \
        --output none \
        2>/dev/null \
        || true

    rm -rf "${TEMP_DIRECTORY}"
}

trap cleanup EXIT


require_environment_variable() {
    local variable_name="$1"

    if [[ -z "${!variable_name:-}" ]]; then
        echo "Required environment variable is missing: ${variable_name}"
        exit 1
    fi
}


wait_for_execution() {
    local job_name="$1"
    local execution_name="$2"
    local expected_status="$3"

    local started_at
    local current_time
    local elapsed_seconds
    local status

    started_at="$(date +%s)"

    while true; do
        status="$(
            az containerapp job execution show \
                --name "${job_name}" \
                --resource-group "${RESOURCE_GROUP}" \
                --job-execution-name "${execution_name}" \
                --query properties.status \
                --output tsv
        )"

        echo "${job_name}/${execution_name}: ${status}"

        if [[ "${status}" == "${expected_status}" ]]; then
            return 0
        fi

        if [[ "${status}" == "Failed" && "${expected_status}" != "Failed" ]]; then
            echo "Execution failed unexpectedly."
            return 1
        fi

        if [[ "${status}" == "Succeeded" && "${expected_status}" != "Succeeded" ]]; then
            echo "Execution succeeded unexpectedly."
            return 1
        fi

        current_time="$(date +%s)"
        elapsed_seconds="$((current_time - started_at))"

        if (( elapsed_seconds >= EXECUTION_TIMEOUT_SECONDS )); then
            echo "Execution polling timed out."
            return 1
        fi

        sleep "${POLL_INTERVAL_SECONDS}"
    done
}


download_latest_pointer() {
    local output_path="$1"

    az storage blob download \
        --account-name "${STORAGE_ACCOUNT}" \
        --container-name "${STORAGE_CONTAINER}" \
        --auth-mode login \
        --name "aqi/latest/pointer.json" \
        --file "${output_path}" \
        --overwrite \
        --output none
}


read_json_value() {
    local json_path="$1"
    local key="$2"

    python - "${json_path}" "${key}" <<'PY'
import json
import sys
from pathlib import Path


path = Path(sys.argv[1])
key = sys.argv[2]

payload = json.loads(
    path.read_text(
        encoding="utf-8"
    )
)

value = payload[key]

if value is None:
    raise SystemExit(
        f"JSON key is null: {key}"
    )

print(value)
PY
}


echo "Phase 10J-F — Failure and recovery validation"
echo "Resource group: ${RESOURCE_GROUP}"
echo "Production job: ${FORECAST_JOB}"
echo "Failure-test job: ${FAILURE_JOB}"


require_environment_variable "HOPSWORKS_API_KEY"
require_environment_variable "HOPSWORKS_PROJECT"
require_environment_variable "HOPSWORKS_HOST"


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


PIPELINE_IMAGE="$(
    az containerapp job show \
        --name "${FORECAST_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query properties.template.containers[0].image \
        --output tsv
)"


API_FQDN="$(
    az containerapp show \
        --name "${API_APP}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query properties.configuration.ingress.fqdn \
        --output tsv
)"


echo
echo "1. Recording the current durable pointer."

download_latest_pointer \
    "${BEFORE_POINTER_PATH}"

BEFORE_RUN_ID="$(
    read_json_value \
        "${BEFORE_POINTER_PATH}" \
        "run_id"
)"

BEFORE_MANIFEST_PATH="$(
    read_json_value \
        "${BEFORE_POINTER_PATH}" \
        "manifest_path"
)"

echo "Current run ID: ${BEFORE_RUN_ID}"
echo "Current manifest: ${BEFORE_MANIFEST_PATH}"


echo
echo "2. Creating an isolated manual failure-test job."

az containerapp job delete \
    --name "${FAILURE_JOB}" \
    --resource-group "${RESOURCE_GROUP}" \
    --yes \
    --output none \
    2>/dev/null \
    || true


az containerapp job create \
    --name "${FAILURE_JOB}" \
    --resource-group "${RESOURCE_GROUP}" \
    --environment "${CONTAINER_ENVIRONMENT}" \
    --trigger-type Manual \
    --replica-timeout 600 \
    --replica-retry-limit 0 \
    --replica-completion-count 1 \
    --parallelism 1 \
    --cpu 0.5 \
    --memory 1.0Gi \
    --image "${PIPELINE_IMAGE}" \
    --container-name failure-test \
    --mi-user-assigned "${IDENTITY_RESOURCE_ID}" \
    --registry-server "${ACR_LOGIN_SERVER}" \
    --registry-identity "${IDENTITY_RESOURCE_ID}" \
    --secrets \
        "invalid-openaq-api-key=phase-10j-f-invalid-key" \
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
        "OPENAQ_API_KEY=secretref:invalid-openaq-api-key" \
        "ALLOW_CACHED_REGISTRY_FALLBACK=true" \
        "ALLOW_LOCAL_MODEL_FALLBACK=true" \
        "AUTOMATIC_RETRAINING_ENABLED=false" \
        "AUTOMATIC_MODEL_PROMOTION_ENABLED=false" \
    --tags \
        "project=pearls-aqi" \
        "environment=staging" \
        "purpose=failure-validation" \
    --output none


echo
echo "3. Starting the controlled failure execution."

FAILURE_EXECUTION_NAME="$(
    az containerapp job start \
        --name "${FAILURE_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query name \
        --output tsv
)"

echo "Failure execution: ${FAILURE_EXECUTION_NAME}"

wait_for_execution \
    "${FAILURE_JOB}" \
    "${FAILURE_EXECUTION_NAME}" \
    "Failed"


echo
echo "4. Confirming that failure did not move the pointer."

download_latest_pointer \
    "${AFTER_FAILURE_POINTER_PATH}"

AFTER_FAILURE_RUN_ID="$(
    read_json_value \
        "${AFTER_FAILURE_POINTER_PATH}" \
        "run_id"
)"

if [[ "${AFTER_FAILURE_RUN_ID}" != "${BEFORE_RUN_ID}" ]]; then
    echo "Failure incorrectly changed the latest pointer."
    exit 1
fi

echo "Pointer remained on: ${AFTER_FAILURE_RUN_ID}"


echo
echo "5. Confirming that the API still serves the existing run."

curl \
    --retry 10 \
    --retry-delay 5 \
    --retry-all-errors \
    --fail \
    --silent \
    "https://${API_FQDN}/api/v1/health/ready" \
    > "${API_AFTER_FAILURE_PATH}"

API_AFTER_FAILURE_RUN_ID="$(
    read_json_value \
        "${API_AFTER_FAILURE_PATH}" \
        "pipeline_run_id"
)"

if [[ "${API_AFTER_FAILURE_RUN_ID}" != "${BEFORE_RUN_ID}" ]]; then
    echo "API no longer serves the last valid run."
    exit 1
fi

echo "API retained valid run: ${API_AFTER_FAILURE_RUN_ID}"


echo
echo "6. Starting the real forecast job for recovery."

RECOVERY_EXECUTION_NAME="$(
    az containerapp job start \
        --name "${FORECAST_JOB}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query name \
        --output tsv
)"

echo "Recovery execution: ${RECOVERY_EXECUTION_NAME}"

wait_for_execution \
    "${FORECAST_JOB}" \
    "${RECOVERY_EXECUTION_NAME}" \
    "Succeeded"


echo
echo "7. Confirming that recovery published a new run."

download_latest_pointer \
    "${AFTER_RECOVERY_POINTER_PATH}"

AFTER_RECOVERY_RUN_ID="$(
    read_json_value \
        "${AFTER_RECOVERY_POINTER_PATH}" \
        "run_id"
)"

AFTER_RECOVERY_MANIFEST_PATH="$(
    read_json_value \
        "${AFTER_RECOVERY_POINTER_PATH}" \
        "manifest_path"
)"

if [[ "${AFTER_RECOVERY_RUN_ID}" == "${BEFORE_RUN_ID}" ]]; then
    echo "Recovery completed but the latest pointer did not advance."
    exit 1
fi

echo "Recovered run ID: ${AFTER_RECOVERY_RUN_ID}"


echo
echo "8. Confirming that the recovery manifest exists."

az storage blob show \
    --account-name "${STORAGE_ACCOUNT}" \
    --container-name "${STORAGE_CONTAINER}" \
    --auth-mode login \
    --name "${AFTER_RECOVERY_MANIFEST_PATH}" \
    --query "{
        Name:name,
        Size:properties.contentLength,
        LastModified:properties.lastModified
    }" \
    --output table


echo
echo "9. Confirming that the API automatically serves the recovered run."

API_REFRESH_DEADLINE="$(( $(date +%s) + 300 ))"

while true; do
    curl \
        --silent \
        "https://${API_FQDN}/api/v1/health/ready" \
        > "${API_AFTER_RECOVERY_PATH}"

    API_AFTER_RECOVERY_RUN_ID="$(
        read_json_value \
            "${API_AFTER_RECOVERY_PATH}" \
            "pipeline_run_id"
    )"

    if [[ "${API_AFTER_RECOVERY_RUN_ID}" == "${AFTER_RECOVERY_RUN_ID}" ]]; then

        break
    fi

    if (( $(date +%s) >= API_REFRESH_DEADLINE )); then

        echo "API did not refresh to the recovered run."
        exit 1
    fi

    echo "API still serves ${API_AFTER_RECOVERY_RUN_ID}; waiting for ${AFTER_RECOVERY_RUN_ID}."

    sleep 15
done


FORECAST_ROWS="$(
    read_json_value \
        "${API_AFTER_RECOVERY_PATH}" \
        "forecast_rows"
)"

if [[ "${FORECAST_ROWS}" != "72" ]]; then
    echo "Recovered API forecast does not contain 72 rows."
    exit 1
fi


echo
echo "10. Writing the Phase 10J-F validation report."

export REPORT_PATH
export RESOURCE_GROUP
export FORECAST_JOB
export FAILURE_JOB
export PIPELINE_IMAGE
export API_FQDN

export FAILURE_EXECUTION_NAME
export RECOVERY_EXECUTION_NAME

export BEFORE_RUN_ID
export AFTER_FAILURE_RUN_ID
export AFTER_RECOVERY_RUN_ID

export BEFORE_MANIFEST_PATH
export AFTER_RECOVERY_MANIFEST_PATH
export FORECAST_ROWS


python - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path


report_path = Path(
    os.environ["REPORT_PATH"]
)

report = {
    "phase": "10J",
    "subphase": "10J-F",
    "generated_at_utc": datetime.now(
        timezone.utc
    ).isoformat(),
    "status": (
        "FORECAST_JOB_FAILURE_RECOVERY_VALIDATED"
    ),
    "resource_group": (
        os.environ["RESOURCE_GROUP"]
    ),
    "production_job": (
        os.environ["FORECAST_JOB"]
    ),
    "failure_test_job": (
        os.environ["FAILURE_JOB"]
    ),
    "pipeline_image": (
        os.environ["PIPELINE_IMAGE"]
    ),
    "api_fqdn": (
        os.environ["API_FQDN"]
    ),
    "failure_execution": {
        "execution_name": (
            os.environ[
                "FAILURE_EXECUTION_NAME"
            ]
        ),
        "expected_status": "Failed",
        "pointer_before": (
            os.environ["BEFORE_RUN_ID"]
        ),
        "pointer_after": (
            os.environ[
                "AFTER_FAILURE_RUN_ID"
            ]
        ),
        "pointer_unchanged": (
            os.environ["BEFORE_RUN_ID"]
            == os.environ[
                "AFTER_FAILURE_RUN_ID"
            ]
        ),
    },
    "recovery_execution": {
        "execution_name": (
            os.environ[
                "RECOVERY_EXECUTION_NAME"
            ]
        ),
        "expected_status": "Succeeded",
        "previous_run_id": (
            os.environ["BEFORE_RUN_ID"]
        ),
        "recovered_run_id": (
            os.environ[
                "AFTER_RECOVERY_RUN_ID"
            ]
        ),
        "pointer_advanced": (
            os.environ["BEFORE_RUN_ID"]
            != os.environ[
                "AFTER_RECOVERY_RUN_ID"
            ]
        ),
        "manifest_path": (
            os.environ[
                "AFTER_RECOVERY_MANIFEST_PATH"
            ]
        ),
    },
    "api_validation": {
        "served_last_valid_run_after_failure": True,
        "automatically_served_recovered_run": True,
        "forecast_rows": int(
            os.environ["FORECAST_ROWS"]
        ),
    },
    "validated_guarantees": {
        "failed_execution_did_not_update_pointer": True,
        "existing_forecast_remained_available": True,
        "successful_recovery_updated_pointer": True,
        "api_refreshed_without_redeployment": True,
        "immutable_manifest_exists": True,
    },
}

report_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

report_path.write_text(
    json.dumps(
        report,
        indent=2,
    ),
    encoding="utf-8",
)

print(
    json.dumps(
        report,
        indent=2,
    )
)

print(
    "Report saved:",
    report_path,
)
PY


echo
echo "Phase 10J-F completed successfully."