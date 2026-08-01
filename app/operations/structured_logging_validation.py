"""Validate structured logging and safe report generation."""

from __future__ import annotations

import argparse
import io
import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.observability.logging import (
    JsonLogFormatter,
)
from app.observability.reports import (
    build_base_report,
    save_operational_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "structured_logging_validation_report.json"
)


def capture_sample_log() -> dict[str, Any]:
    """Create and capture one sample structured log."""

    stream = io.StringIO()

    handler = logging.StreamHandler(
        stream
    )

    handler.setFormatter(
        JsonLogFormatter()
    )

    logger = logging.getLogger(
        "phase10e-validation"
    )

    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    logger.info(
        "Validation pipeline completed.",
        extra={
            "event": "pipeline_completed",
            "service_name": "pipeline",
            "environment": "development",
            "pipeline_name": (
                "phase10e_validation"
            ),
            "pipeline_run_id": (
                "phase10e-test-run"
            ),
            "status": "COMPLETED",
            "duration_seconds": 1.25,
            "row_count": 72,
            "api_key": (
                "must-not-be-visible"
            ),
        },
    )

    handler.flush()

    line = stream.getvalue().strip()

    payload = json.loads(line)

    return {
        "raw_line": line,
        "payload": payload,
    }


def run_structured_logging_validation() -> dict[str, Any]:
    """Validate JSON logging and report redaction."""

    sample_log = capture_sample_log()

    payload = sample_log["payload"]

    with tempfile.TemporaryDirectory(
        prefix="phase10e-report-"
    ) as temporary_directory:
        report_path = (
            Path(temporary_directory)
            / "report.json"
        )

        source_report = build_base_report(
            phase="10E",
            operation_name=(
                "structured_logging_validation"
            ),
            status="COMPLETED",
            environment="development",
            service_name="validation",
            run_id="phase10e-test-run",
        )

        source_report.update(
            {
                "row_count": 72,
                "api_key": "hidden-value",
                "nested": {
                    "password": (
                        "hidden-password"
                    ),
                    "safe_value": "visible",
                },
            }
        )

        save_operational_report(
            report=source_report,
            path=report_path,
        )

        saved_report = json.loads(
            report_path.read_text(
                encoding="utf-8"
            )
        )

    checks = {
        "log_is_valid_json": (
            isinstance(payload, dict)
        ),
        "timestamp_present": bool(
            payload.get("timestamp_utc")
        ),
        "level_present": (
            payload.get("level")
            == "INFO"
        ),
        "event_present": (
            payload.get("event")
            == "pipeline_completed"
        ),
        "run_id_present": (
            payload.get(
                "pipeline_run_id"
            )
            == "phase10e-test-run"
        ),
        "row_count_present": (
            payload.get("row_count")
            == 72
        ),
        "log_secret_redacted": (
            payload.get("api_key")
            == "[REDACTED]"
        ),
        "report_secret_redacted": (
            saved_report.get("api_key")
            == "[REDACTED]"
        ),
        "nested_secret_redacted": (
            saved_report[
                "nested"
            ]["password"]
            == "[REDACTED]"
        ),
        "safe_value_preserved": (
            saved_report[
                "nested"
            ]["safe_value"]
            == "visible"
        ),
    }

    approved = all(
        checks.values()
    )

    return {
        "phase": "10E",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": (
            "STRUCTURED_LOGGING_VALIDATED"
            if approved
            else "STRUCTURED_LOGGING_INVALID"
        ),
        "approved": approved,
        "checks": checks,
        "required_fields": [
            "timestamp_utc",
            "level",
            "service_name",
            "environment",
            "event",
            "pipeline_name",
            "pipeline_run_id",
            "status",
            "duration_seconds",
            "row_count",
            "model_version",
            "error_code",
        ],
        "secret_values_included": False,
        "azure_resources_created": False,
    }


def save_validation_report(
    report: dict[str, Any],
) -> Path:
    """Save the Phase 10E validation report."""

    return save_operational_report(
        report=report,
        path=REPORT_PATH,
    )


def main() -> int:
    """Run validation."""

    parser = argparse.ArgumentParser(
        description=(
            "Validate structured logging and "
            "safe operational reports."
        )
    )

    parser.parse_args()

    try:
        report = (
            run_structured_logging_validation()
        )

        exit_code = (
            0
            if report["approved"]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10E",
            "generated_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": (
                "STRUCTURED_LOGGING_VALIDATION_FAILED"
            ),
            "approved": False,
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(error),
            "secret_values_included": False,
            "azure_resources_created": False,
        }

        exit_code = 1

    report_path = save_validation_report(
        report
    )

    print(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )

    print(
        "Report saved:",
        report_path,
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())