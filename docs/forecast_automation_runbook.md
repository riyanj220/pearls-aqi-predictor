# Pearls AQI Forecast Automation Runbook

## Purpose

This runbook documents the scheduled 72-hour PM2.5 and AQI forecast
publication workflow deployed on Azure.

The automated workflow fetches live data, loads the approved model, generates
the forecast, calculates AQI and alerts, publishes immutable artifacts to
Azure Blob Storage, and allows the FastAPI service to serve the latest
validated run.

## Architecture

```text
Azure Container Apps scheduled job
        |
        | python -m app.pipelines.publish_forecast
        v
Live OpenAQ PM2.5 + Open-Meteo weather
        |
        v
Hopsworks production model
        |
        v
72-hour PM2.5 forecast
        |
        v
AQI and alert pipeline
        |
        v
Immutable Azure Blob run + manifest
        |
        v
aqi/latest/pointer.json
        |
        v
Blob-backed FastAPI service
        |
        v
Streamlit dashboard
```
