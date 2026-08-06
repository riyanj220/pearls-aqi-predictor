#!/usr/bin/env bash

set -euo pipefail

echo "Starting production health inspection."
echo "Started at UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"

python -m app.operations.persist_production_health

exit_code=$?

echo "Production health inspection exited with: ${exit_code}"
echo "Finished at UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"

exit "${exit_code}"