#!/usr/bin/env bash

set -Eeuo pipefail


RESOURCE_GROUP="${
    RESOURCE_GROUP:-rg-pearls-aqi-prod
}"

FEATURE_JOB="${
    FEATURE_JOB:-job-pearls-aqi-features-prod
}"

FORECAST_JOB="${
    FORECAST_JOB:-job-pearls-aqi-forecast-prod
}"

RETRAINING_JOB="${
    RETRAINING_JOB:-job-pearls-aqi-retraining-prod
}"

MONITORING_JOB="${
    MONITORING_JOB:-job-pearls-aqi-monitoring-prod
}"


wait_for_execution() {
    local job_name="$1"
    local execution_name="$2"

    echo
    echo "Waiting for:"
    echo "  Job:       ${job_name}"
    echo "  Execution: ${execution_name}"

    while true; do
        status="$(
            az containerapp job execution show \
                --resource-group "${RESOURCE_GROUP}" \
                --name "${job_name}" \
                --job-execution-name "${execution_name}" \
                --query properties.status \
                --output tsv
        )"

        echo "Status: ${status}"

        case "${status}" in
            Succeeded)
                echo \
                    "${job_name} completed successfully."
                return 0
                ;;

            Failed|Stopped|Degraded)
                echo \
                    "${job_name} execution failed." \
                    >&2

                return 1
                ;;
        esac

        sleep 15
    done
}


start_and_wait() {
    local job_name="$1"

    echo
    echo "Starting ${job_name}..."

    execution_name="$(
        az containerapp job start \
            --resource-group "${RESOURCE_GROUP}" \
            --name "${job_name}" \
            --query name \
            --output tsv
    )"

    if [[ -z "${execution_name}" ]]; then
        echo \
            "Could not resolve execution name for ${job_name}." \
            >&2

        return 1
    fi

    echo "Execution: ${execution_name}"

    wait_for_execution \
        "${job_name}" \
        "${execution_name}"

    printf '%s\n' \
        "${execution_name}"
}


echo
echo "========================================"
echo "Initial production execution"
echo "========================================"


# ---------------------------------------------------------------------------
# 1. Feature synchronization
# ---------------------------------------------------------------------------

FEATURE_EXECUTION="$(
    start_and_wait \
        "${FEATURE_JOB}"
)"


# ---------------------------------------------------------------------------
# 2. Forecast publication
# ---------------------------------------------------------------------------

FORECAST_EXECUTION="$(
    start_and_wait \
        "${FORECAST_JOB}"
)"


# ---------------------------------------------------------------------------
# 3. Retraining eligibility / orchestration
# ---------------------------------------------------------------------------

RETRAINING_EXECUTION="$(
    start_and_wait \
        "${RETRAINING_JOB}"
)"


# ---------------------------------------------------------------------------
# 4. Production monitoring
# ---------------------------------------------------------------------------

MONITORING_EXECUTION="$(
    start_and_wait \
        "${MONITORING_JOB}"
)"


echo
echo "========================================"
echo "Initial production execution complete"
echo "========================================"

echo
echo "Feature execution:"
echo "  ${FEATURE_EXECUTION}"

echo
echo "Forecast execution:"
echo "  ${FORECAST_EXECUTION}"

echo
echo "Retraining execution:"
echo "  ${RETRAINING_EXECUTION}"

echo
echo "Monitoring execution:"
echo "  ${MONITORING_EXECUTION}"