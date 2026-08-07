#!/usr/bin/env bash

set -Eeuo pipefail

: "${PRODUCTION_RESOURCE_GROUP:?PRODUCTION_RESOURCE_GROUP is required}"
: "${FEATURE_JOB_NAME:?FEATURE_JOB_NAME is required}"
: "${FORECAST_JOB_NAME:?FORECAST_JOB_NAME is required}"
: "${RETRAINING_JOB_NAME:?RETRAINING_JOB_NAME is required}"

echo "Starting production health inspection."
echo "Started at UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"

python -m app.operations.persist_production_health \
    --resource-group "${PRODUCTION_RESOURCE_GROUP}" \
    --feature-job-name "${FEATURE_JOB_NAME}" \
    --forecast-job-name "${FORECAST_JOB_NAME}" \
    --retraining-job-name "${RETRAINING_JOB_NAME}"

echo "Production health inspection completed."
echo "Finished at UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"