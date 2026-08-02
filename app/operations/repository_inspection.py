"""Inspect repository deployment assets and operational commands."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class FileInspection:
    """Inspection result for one expected repository file."""

    name: str
    path: str
    exists: bool
    required: bool


@dataclass(frozen=True)
class CommandInspection:
    """Inspection result for one operational command."""

    name: str
    command: str
    purpose: str
    category: str
    non_interactive: bool
    expected_report: str | None
    expected_success_statuses: list[str]
    available: bool
    validation_note: str


EXPECTED_FILES: tuple[
    tuple[str, str, bool],
    ...,
] = (
    (
        "FastAPI production Dockerfile",
        "Dockerfile.api",
        True,
    ),
    (
        "Streamlit production Dockerfile",
        "Dockerfile.dashboard",
        True,
    ),
    (
        "Pipeline production Dockerfile",
        "Dockerfile.pipeline",
        True,
    ),
    (
        "Production Docker Compose",
        "compose.production.yml",
        True,
    ),
    (
        "Development Docker Compose",
        "compose.yaml",
        False,
    ),
    (
        "Python project configuration",
        "pyproject.toml",
        True,
    ),
    (
        "Locked dependencies",
        "uv.lock",
        True,
    ),
    (
        "Environment template",
        ".env.example",
        True,
    ),
    (
        "FastAPI application",
        "app/api/main.py",
        True,
    ),
    (
        "Streamlit application",
        "dashboard/app.py",
        True,
    ),
    (
        "Live inference notebook",
        "notebooks/06_live_inference_pipeline.ipynb",
        True,
    ),
    (
        "AQI pipeline notebook",
        "notebooks/07_build_aqi_alert_pipeline.ipynb",
        False,
    ),
    (
        "Phase 9 notebook",
        "notebooks/10_build_hopsworks_mlops_pipeline.ipynb",
        True,
    ),
    (
        "Incremental feature pipeline",
        "app/pipelines/incremental_features.py",
        True,
    ),
    (
        "Historical backfill pipeline",
        "app/pipelines/historical_backfill.py",
        True,
    ),
    (
        "Training-dataset pipeline",
        "app/pipelines/build_training_dataset.py",
        True,
    ),
    (
        "Retraining pipeline",
        "app/pipelines/retraining_cycle.py",
        True,
    ),
    (
        "Champion–challenger pipeline",
        "app/pipelines/champion_challenger.py",
        True,
    ),
    (
        "Registry inference validation",
        "app/pipelines/validate_registry_inference.py",
        True,
    ),
    (
        "FastAPI tests",
        "tests/api",
        True,
    ),
    (
        "Dashboard tests",
        "tests/dashboard",
        True,
    ),
    (
        "Live inference pipeline",
        "app/pipelines/live_inference.py",
        True,
    ),
    (
        "AQI and alert pipeline",
        "app/pipelines/aqi_alert_pipeline.py",
        True,
    ),
)


OPERATIONAL_COMMANDS: tuple[
    dict[str, Any],
    ...,
] = (
    {
        "name": "Run complete test suite",
        "command": "uv run pytest -v",
        "purpose": (
            "Run the complete automated test suite."
        ),
        "category": "validation",
        "non_interactive": True,
        "expected_report": None,
        "expected_success_statuses": [
            "exit_code_0",
        ],
        "required_paths": [
            "tests",
            "pyproject.toml",
        ],
        "validation_note": (
            "Suitable for CI when tests do not call "
            "live external services."
        ),
    },
    {
        "name": "Run Ruff lint checks",
        "command": "uv run ruff check .",
        "purpose": (
            "Validate Python lint rules."
        ),
        "category": "validation",
        "non_interactive": True,
        "expected_report": None,
        "expected_success_statuses": [
            "exit_code_0",
        ],
        "required_paths": [
            "pyproject.toml",
        ],
        "validation_note": (
            "Use only when Ruff is configured in the project."
        ),
    },
    {
        "name": "Run Ruff formatting check",
        "command": "uv run ruff format --check .",
        "purpose": (
            "Validate formatting without modifying files."
        ),
        "category": "validation",
        "non_interactive": True,
        "expected_report": None,
        "expected_success_statuses": [
            "exit_code_0",
        ],
        "required_paths": [
            "pyproject.toml",
        ],
        "validation_note": (
            "Safe for CI because it performs no writes."
        ),
    },
    {
        "name": "Start FastAPI",
        "command": (
            "uv run uvicorn app.api.main:app "
            "--host 0.0.0.0 --port 8000"
        ),
        "purpose": (
            "Start the FastAPI serving application."
        ),
        "category": "serving",
        "non_interactive": True,
        "expected_report": None,
        "expected_success_statuses": [
            "process_running",
        ],
        "required_paths": [
            "app/api/main.py",
        ],
        "validation_note": (
            "Long-running serving command."
        ),
    },
    {
        "name": "Start Streamlit",
        "command": (
            "uv run streamlit run dashboard/app.py "
            "--server.address=0.0.0.0 "
            "--server.port=8501 "
            "--server.headless=true"
        ),
        "purpose": (
            "Start the Streamlit dashboard."
        ),
        "category": "serving",
        "non_interactive": True,
        "expected_report": None,
        "expected_success_statuses": [
            "process_running",
        ],
        "required_paths": [
            "dashboard/app.py",
        ],
        "validation_note": (
            "Requires a reachable FastAPI base URL."
        ),
    },
    {
        "name": "Validate registry model resolution",
        "command": (
            "uv run python -m "
            "app.pipelines.validate_registry_inference"
        ),
        "purpose": (
            "Resolve the configured production model "
            "and validate checksum and feature contract."
        ),
        "category": "mlops",
        "non_interactive": True,
        "expected_report": (
            "reports/phase_9/"
            "production_model_resolution_report.json"
        ),
        "expected_success_statuses": [
            "REGISTRY_MODEL_LOADING_VALIDATED",
        ],
        "required_paths": [
            "app/pipelines/"
            "validate_registry_inference.py",
        ],
        "validation_note": (
            "Requires Hopsworks credentials when registry "
            "mode is enabled."
        ),
    },
    {
        "name": "Run incremental feature synchronization",
        "command": (
            "uv run python -m "
            "app.pipelines.incremental_features"
        ),
        "purpose": (
            "Synchronize recent validated feature rows "
            "with Hopsworks."
        ),
        "category": "batch",
        "non_interactive": True,
        "expected_report": (
            "reports/phase_9/"
            "incremental_feature_report.json"
        ),
        "expected_success_statuses": [
            "INCREMENTAL_SYNC_DRY_RUN_SUCCESS",
            "INCREMENTAL_SYNC_SUCCESS",
        ],
        "required_paths": [
            "app/pipelines/incremental_features.py",
        ],
        "validation_note": (
            "Successful no-op runs may write zero rows."
        ),
    },
    {
        "name": "Run historical backfill",
        "command": (
            "uv run python -m "
            "app.pipelines.historical_backfill "
            "--start <UTC_START> --end <UTC_END>"
        ),
        "purpose": (
            "Backfill a bounded historical period."
        ),
        "category": "batch",
        "non_interactive": True,
        "expected_report": (
            "reports/phase_9/"
            "historical_backfill_report.json"
        ),
        "expected_success_statuses": [
            "BACKFILL_DRY_RUN_SUCCESS",
            "BACKFILL_SUCCESS",
        ],
        "required_paths": [
            "app/pipelines/historical_backfill.py",
        ],
        "validation_note": (
            "Dates must be provided explicitly. "
            "Production workflows should default to dry-run."
        ),
    },
    {
        "name": "Build training dataset",
        "command": (
            "uv run python -m "
            "app.pipelines.build_training_dataset"
        ),
        "purpose": (
            "Build and validate the Hopsworks-backed "
            "training dataset."
        ),
        "category": "mlops",
        "non_interactive": True,
        "expected_report": (
            "reports/phase_9/"
            "training_dataset_report.json"
        ),
        "expected_success_statuses": [
            "TRAINING_DATASET_PARITY_PASSED",
        ],
        "required_paths": [
            "app/pipelines/build_training_dataset.py",
        ],
        "validation_note": (
            "Requires the configured Hopsworks feature view."
        ),
    },
    {
        "name": "Run retraining eligibility",
        "command": (
            "uv run python -m "
            "app.pipelines.retraining_cycle"
        ),
        "purpose": (
            "Check eligibility and train only when enough "
            "new labeled data exists."
        ),
        "category": "mlops",
        "non_interactive": True,
        "expected_report": (
            "reports/phase_9/"
            "automated_training_report.json"
        ),
        "expected_success_statuses": [
            "RETRAINING_COMPLETED",
            "RETRAINING_SKIPPED_NO_NEW_DATA",
        ],
        "required_paths": [
            "app/pipelines/retraining_cycle.py",
        ],
        "validation_note": (
            "Scheduled production runs must not use --force."
        ),
    },
    {
        "name": "Run forced candidate retraining",
        "command": (
            "uv run python -m "
            "app.pipelines.retraining_cycle --force"
        ),
        "purpose": (
            "Run controlled manual candidate training."
        ),
        "category": "administration",
        "non_interactive": True,
        "expected_report": (
            "reports/phase_9/"
            "automated_training_report.json"
        ),
        "expected_success_statuses": [
            "RETRAINING_COMPLETED",
        ],
        "required_paths": [
            "app/pipelines/retraining_cycle.py",
        ],
        "validation_note": (
            "Manual protected operation only."
        ),
    },
    {
        "name": "Evaluate latest challenger",
        "command": (
            "uv run python -m "
            "app.pipelines.champion_challenger"
        ),
        "purpose": (
            "Compare the latest challenger with the "
            "current champion."
        ),
        "category": "mlops",
        "non_interactive": True,
        "expected_report": (
            "reports/phase_9/"
            "champion_challenger_report.json"
        ),
        "expected_success_statuses": [
            "CHALLENGER_APPROVED",
            "CHALLENGER_REJECTED",
        ],
        "required_paths": [
            "app/pipelines/champion_challenger.py",
        ],
        "validation_note": (
            "Rejection is a safe successful result."
        ),
    },
    {
        "name": "Register approved challenger",
        "command": (
            "uv run python -m "
            "app.pipelines.champion_challenger "
            "--register-approved"
        ),
        "purpose": (
            "Register a challenger only after all "
            "promotion gates pass."
        ),
        "category": "administration",
        "non_interactive": True,
        "expected_report": (
            "reports/phase_9/"
            "champion_challenger_report.json"
        ),
        "expected_success_statuses": [
            "CHALLENGER_REGISTERED",
        ],
        "required_paths": [
            "app/pipelines/champion_challenger.py",
        ],
        "validation_note": (
            "Protected manual operation. "
            "Must not auto-promote production."
        ),
    },
    {
        "name": "Build production container images",
        "command": (
            "docker compose "
            "--file compose.production.yml "
            "--profile jobs build"
        ),
        "purpose": (
            "Build the production FastAPI, Streamlit, "
            "and batch-pipeline images."
        ),
        "category": "container",
        "non_interactive": True,
        "expected_report": None,
        "expected_success_statuses": [
            "exit_code_0",
        ],
        "validation_note": (
            "Builds all three Phase 10G production images."
        ),
    },
    {
        "name": "Run live 72-hour inference",
        "command": (
            "uv run python -m "
            "app.pipelines.live_inference"
        ),
        "purpose": (
            "Fetch live sources, build features, resolve "
            "the production model, and generate a "
            "72-hour PM2.5 forecast."
        ),
        "category": "batch",
        "non_interactive": True,
        "expected_report": (
            "reports/phase_10/"
            "live_inference_pipeline_report.json"
        ),
        "expected_success_statuses": [
            "LIVE_INFERENCE_COMPLETED",
        ],
        "required_paths": [
            "app/pipelines/live_inference.py",
        ],
        "validation_note": (
            "Requires OpenAQ access and live Open-Meteo data."
        ),
    },
    {
        "name": "Run AQI and alert processing",
        "command": (
            "uv run python -m "
            "app.pipelines.aqi_alert_pipeline"
        ),
        "purpose": (
            "Enrich the newest successful PM2.5 forecast "
            "with AQI, health guidance, and alerts."
        ),
        "category": "batch",
        "non_interactive": True,
        "expected_report": (
            "reports/phase_10/"
            "aqi_alert_pipeline_report.json"
        ),
        "expected_success_statuses": [
            "AQI_ALERT_PIPELINE_COMPLETED",
        ],
        "required_paths": [
            "app/pipelines/aqi_alert_pipeline.py",
        ],
        "validation_note": (
            "Consumes one complete successful Phase 5 run."
        ),
    },
)


HEALTH_ENDPOINTS: tuple[
    dict[str, str],
    ...,
] = (
    {
        "name": "FastAPI liveness",
        "path": "/api/v1/health/live",
        "expected_behavior": "HTTP 200",
    },
    {
        "name": "FastAPI readiness",
        "path": "/api/v1/health/ready",
        "expected_behavior": (
            "HTTP 200 when ready; structured non-ready "
            "response when artifacts are unavailable or stale"
        ),
    },
    {
        "name": "Forecast",
        "path": "/api/v1/forecast",
        "expected_behavior": (
            "HTTP 200 with 72 rows when current artifacts "
            "are valid"
        ),
    },
    {
        "name": "Forecast summary",
        "path": "/api/v1/forecast/summary",
        "expected_behavior": "HTTP 200",
    },
    {
        "name": "Alerts",
        "path": "/api/v1/alerts",
        "expected_behavior": "HTTP 200",
    },
    {
        "name": "Metadata",
        "path": "/api/v1/metadata",
        "expected_behavior": "HTTP 200",
    },
    {
        "name": "Streamlit process health",
        "path": "/_stcore/health",
        "expected_behavior": "HTTP 200",
    },
)


def inspect_expected_files() -> list[FileInspection]:
    """Inspect expected operational files and directories."""

    results: list[FileInspection] = []

    for name, relative_path, required in EXPECTED_FILES:
        path = PROJECT_ROOT / relative_path

        results.append(
            FileInspection(
                name=name,
                path=relative_path,
                exists=path.exists(),
                required=required,
            )
        )

    return results


def inspect_command(
    command: dict[str, Any],
) -> CommandInspection:
    """Inspect whether a command's required files exist."""

    required_paths = command.get(
        "required_paths",
        [],
    )

    available = all(
        (PROJECT_ROOT / path).exists()
        for path in required_paths
    )

    return CommandInspection(
        name=str(command["name"]),
        command=str(command["command"]),
        purpose=str(command["purpose"]),
        category=str(command["category"]),
        non_interactive=bool(
            command["non_interactive"]
        ),
        expected_report=command.get(
            "expected_report"
        ),
        expected_success_statuses=list(
            command["expected_success_statuses"]
        ),
        available=available,
        validation_note=str(
            command["validation_note"]
        ),
    )


def inspect_commands() -> list[CommandInspection]:
    """Inspect all operational command contracts."""

    return [
        inspect_command(command)
        for command in OPERATIONAL_COMMANDS
    ]


def get_git_commit_sha() -> str | None:
    """Return the current Git commit SHA when available."""

    try:
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "HEAD",
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

        return result.stdout.strip() or None

    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None


def discover_artifact_directories() -> dict[str, Any]:
    """Inspect current local artifact directories."""

    artifact_paths = {
        "canonical_data": "data/processed",
        "training_data": "data/training",
        "models": "models",
        "inference_runs": "inference/runs",
        "inference_latest": "inference/latest",
        "aqi_runs": "aqi/runs",
        "aqi_latest": "aqi/latest",
        "phase_9_reports": "reports/phase_9",
        "phase_10_reports": "reports/phase_10",
    }

    result: dict[str, Any] = {}

    for name, relative_path in artifact_paths.items():
        path = PROJECT_ROOT / relative_path

        result[name] = {
            "path": relative_path,
            "exists": path.exists(),
            "file_count": (
                sum(
                    1
                    for item in path.rglob("*")
                    if item.is_file()
                )
                if path.exists()
                else 0
            ),
        }

    return result


def discover_workflows() -> list[str]:
    """Return existing GitHub Actions workflow files."""

    workflow_directory = (
        PROJECT_ROOT
        / ".github"
        / "workflows"
    )

    if not workflow_directory.exists():
        return []

    return sorted(
        path.relative_to(
            PROJECT_ROOT
        ).as_posix()
        for path in workflow_directory.glob(
            "*.y*ml"
        )
        if path.is_file()
    )


def build_repository_operations_report() -> dict[str, Any]:
    """Build the complete Phase 10A report."""

    files = inspect_expected_files()
    commands = inspect_commands()

    missing_required_files = [
        file.path
        for file in files
        if file.required and not file.exists
    ]

    unavailable_commands = [
        command.name
        for command in commands
        if not command.available
    ]

    interactive_commands = [
        command.name
        for command in commands
        if not command.non_interactive
    ]

    serving_commands = [
        asdict(command)
        for command in commands
        if command.category == "serving"
    ]

    batch_commands = [
        asdict(command)
        for command in commands
        if command.category
        in {
            "batch",
            "mlops",
            "administration",
        }
    ]

    inspection_passed = all(
        [
            not missing_required_files,
            not interactive_commands,
        ]
    )

    return {
        "phase": "10A",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "REPOSITORY_OPERATIONS_INSPECTION_COMPLETED"
            if inspection_passed
            else "REPOSITORY_OPERATIONS_INSPECTION_INCOMPLETE"
        ),
        "project_root": str(PROJECT_ROOT),
        "git_commit_sha": get_git_commit_sha(),
        "python_version": sys.version.split()[0],
        "files": [
            asdict(file)
            for file in files
        ],
        "missing_required_files": (
            missing_required_files
        ),
        "commands": [
            asdict(command)
            for command in commands
        ],
        "unavailable_commands": (
            unavailable_commands
        ),
        "interactive_commands": (
            interactive_commands
        ),
        "serving_commands": serving_commands,
        "batch_commands": batch_commands,
        "health_endpoints": list(
            HEALTH_ENDPOINTS
        ),
        "artifact_directories": (
            discover_artifact_directories()
        ),
        "existing_github_workflows": (
            discover_workflows()
        ),
        "operational_boundaries": {
            "serving_requests_launch_batch_jobs": False,
            "streamlit_reads_fastapi_only": True,
            "scheduled_jobs_run_outside_fastapi": True,
            "scheduled_jobs_run_outside_streamlit": True,
            "latest_artifacts_should_update_only_after_success": True,
        },
        "identified_gaps": [],
        "recommended_next_actions": [],
        "phase_10a_approved": inspection_passed,
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Save the Phase 10A report."""

    report_path = (
        PROJECT_ROOT
        / "reports"
        / "phase_10"
        / "repository_operations_report.json"
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return report_path


def main() -> int:
    """Run repository inspection."""

    parser = argparse.ArgumentParser(
        description=(
            "Inspect production operations and "
            "deployment readiness."
        )
    )

    parser.parse_args()

    report = build_repository_operations_report()
    report_path = save_report(report)

    print(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )

    print("Report saved:", report_path)

    return (
        0
        if report["phase_10a_approved"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())