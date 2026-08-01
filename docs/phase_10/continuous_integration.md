# Pearls AQI Predictor — Continuous Integration

## Purpose

Continuous integration validates code quality, operational contracts,
automated tests, and container builds before deployment.

## Triggers

The CI workflow runs on:

- pull requests
- pushes to `main`
- manual workflow dispatch

## Python validation

The workflow performs:

- uv lockfile verification
- locked dependency installation
- targeted Ruff linting
- targeted formatting validation
- Python module compilation
- operational validation commands
- automated tests

## External-service boundary

Routine CI does not connect to:

- OpenAQ
- Open-Meteo
- Hopsworks
- Azure Blob Storage
- Azure Key Vault

Configuration validation uses placeholder values only.

## Container validation

The workflow validates Docker Compose and builds:

- the FastAPI image
- the Streamlit image

Images are not pushed to Azure Container Registry during CI.

Registry publishing is handled separately in Phase 10H.

## Ruff scope

Repository-wide Ruff enforcement is deferred because older project files
contain existing style violations.

Phase 10 production and operations modules are enforced immediately.

The linting scope can be expanded gradually after historical violations are
resolved.

## Secrets

Routine CI requires no application secrets.

GitHub Actions must not receive production OpenAQ, Hopsworks, Storage, or Key
Vault credentials during this phase.
