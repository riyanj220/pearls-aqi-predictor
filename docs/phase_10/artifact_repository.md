# Pearls AQI Predictor — Artifact Repository

## Purpose

The artifact repository provides one storage contract for local development and
Azure deployment.

Local development uses the filesystem.

Azure deployment uses Blob Storage through passwordless Microsoft Entra
authentication.

## Artifact layout

```text
inference/
  runs/
    <pipeline_run_id>/
      forecast.parquet
      forecast.csv
      feature_matrix.parquet
      pm25_input.parquet
      weather_input.parquet
      run_metadata.json
      validation_report.json
      manifest.json

  latest/
    pointer.json

aqi/
  runs/
    <phase_6_run_id>/
      forecast.parquet
      alert_episodes.parquet
      forecast_summary.json
      metadata.json
      validation_report.json
      manifest.json

  latest/
    pointer.json
```
