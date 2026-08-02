# Pearls AQI Predictor — Staging Deployment

## Environment

The staging environment runs in Azure Container Apps Consumption in Central
India.

The environment uses:

- scale-to-zero
- one maximum replica per HTTP service
- no Log Analytics workspace
- user-assigned managed identity
- immutable Azure Container Registry image tags

## Applications

The environment contains:

- FastAPI staging application
- Streamlit staging application

The pipeline image is not deployed as a scheduled job in Phase 10I.

Scheduled inference and AQI processing are introduced in Phase 10J.

## Registry authentication

The Container Apps use a user-assigned managed identity with the `AcrPull`
role on the existing Azure Container Registry.

No registry password or administrator account is used.

## Storage

A Standard LRS StorageV2 account and private Blob container are created.

The managed identity receives `Storage Blob Data Contributor`.

The Blob repository will be used by scheduled pipelines in later phases.

## Staging freshness

The staging API temporarily accepts older embedded artifacts so infrastructure
can be validated without repeatedly publishing a new image.

Production will restore strict freshness thresholds after scheduled artifact
publication is active.

## Cost controls

- Consumption plan
- minimum replicas set to zero
- maximum replicas set to one
- Central India region
- Standard LRS storage
- no Log Analytics workspace
- no dedicated workload profile
