#!/usr/bin/env bash

set -Eeuo pipefail

ACR_NAME="${ACR_NAME:-walpole}"
ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-walpole.azurecr.io}"

LOCAL_IMAGE_TAG="${LOCAL_IMAGE_TAG:-}"
REGISTRY_IMAGE_TAG="${REGISTRY_IMAGE_TAG:-}"

if [[ -z "${LOCAL_IMAGE_TAG}" ]]; then
    echo "LOCAL_IMAGE_TAG is required." >&2
    exit 1
fi

if [[ -z "${REGISTRY_IMAGE_TAG}" ]]; then
    echo "REGISTRY_IMAGE_TAG is required." >&2
    exit 1
fi

LOCAL_API_IMAGE="pearls-aqi-api:${LOCAL_IMAGE_TAG}"
LOCAL_DASHBOARD_IMAGE="pearls-aqi-dashboard:${LOCAL_IMAGE_TAG}"
LOCAL_PIPELINE_IMAGE="pearls-aqi-pipeline:${LOCAL_IMAGE_TAG}"

REMOTE_API_IMAGE="${ACR_LOGIN_SERVER}/pearls-aqi/api:${REGISTRY_IMAGE_TAG}"
REMOTE_DASHBOARD_IMAGE="${ACR_LOGIN_SERVER}/pearls-aqi/dashboard:${REGISTRY_IMAGE_TAG}"
REMOTE_PIPELINE_IMAGE="${ACR_LOGIN_SERVER}/pearls-aqi/pipeline:${REGISTRY_IMAGE_TAG}"

required_images=(
    "${LOCAL_API_IMAGE}"
    "${LOCAL_DASHBOARD_IMAGE}"
    "${LOCAL_PIPELINE_IMAGE}"
)

for image in "${required_images[@]}"; do
    if ! docker image inspect "${image}" >/dev/null 2>&1; then
        echo "Required local image does not exist: ${image}" >&2
        exit 1
    fi
done

echo "Authenticating with Azure Container Registry..."
az acr login \
    --name "${ACR_NAME}"

echo "Tagging API image..."
docker tag \
    "${LOCAL_API_IMAGE}" \
    "${REMOTE_API_IMAGE}"

echo "Tagging dashboard image..."
docker tag \
    "${LOCAL_DASHBOARD_IMAGE}" \
    "${REMOTE_DASHBOARD_IMAGE}"

echo "Tagging pipeline image..."
docker tag \
    "${LOCAL_PIPELINE_IMAGE}" \
    "${REMOTE_PIPELINE_IMAGE}"

echo "Pushing API image..."
docker push "${REMOTE_API_IMAGE}"

echo "Pushing dashboard image..."
docker push "${REMOTE_DASHBOARD_IMAGE}"

echo "Pushing pipeline image..."
docker push "${REMOTE_PIPELINE_IMAGE}"

echo
echo "Published images:"
printf '%s\n' \
    "${REMOTE_API_IMAGE}" \
    "${REMOTE_DASHBOARD_IMAGE}" \
    "${REMOTE_PIPELINE_IMAGE}"