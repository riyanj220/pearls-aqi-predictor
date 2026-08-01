# Pearls AQI Predictor — Structured Logging

## Format

Every application log is emitted as one JSON object per line.

Common fields include:

- `timestamp_utc`
- `level`
- `service_name`
- `environment`
- `event`
- `pipeline_name`
- `pipeline_run_id`
- `status`
- `duration_seconds`
- `row_count`
- `model_version`
- `error_code`

## Pipeline run ID

The pipeline run ID connects:

- inference logs
- AQI logs
- run artifacts
- manifests
- validation reports
- deployment investigations

## Secret protection

Fields whose names indicate credentials are redacted.

Examples include:

- API keys
- passwords
- authorization headers
- access tokens
- secrets
- connection strings
- storage keys

Complete environment dictionaries must not be logged.

## Error codes

Operational failures use stable error codes rather than relying only on
exception messages.

Examples:

- `SOURCE_API_FAILURE`
- `SOURCE_DATA_STALE`
- `MODEL_RESOLUTION_FAILED`
- `INFERENCE_FAILED`
- `AQI_PIPELINE_FAILED`
- `ARTIFACT_PUBLICATION_FAILED`
- `MODEL_TRAINING_FAILED`
- `DEPLOYMENT_FAILED`

## Reporting

Operational JSON reports are written atomically through a temporary file.

Sensitive values are redacted before report serialization.
