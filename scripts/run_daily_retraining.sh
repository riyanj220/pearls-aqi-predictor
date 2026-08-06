#!/usr/bin/env bash

set -euo pipefail

echo "Starting production-safe daily retraining workflow."
echo "Started at UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"

python -m app.pipelines.daily_retraining

exit_code=$?

echo "Daily retraining finished with exit code: ${exit_code}"
echo "Finished at UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"

exit "${exit_code}"