"""Shared helpers for safe operational JSON reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.observability.logging import (
    sanitize_value,
)


class OperationalReportError(RuntimeError):
    """Raised when an operational report cannot be saved."""


def build_base_report(
    *,
    phase: str,
    operation_name: str,
    status: str,
    environment: str,
    service_name: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build common operational report metadata."""

    return {
        "phase": phase,
        "operation_name": operation_name,
        "status": status,
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "environment": environment,
        "service_name": service_name,
        "run_id": run_id,
    }


def sanitize_report(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Remove sensitive values from a report."""

    return {
        str(name): sanitize_value(
            str(name),
            value,
        )
        for name, value in report.items()
    }


def save_operational_report(
    *,
    report: Mapping[str, Any],
    path: Path,
) -> Path:
    """Save a redacted JSON report atomically."""

    safe_report = sanitize_report(
        report
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    try:
        temporary_path.write_text(
            json.dumps(
                safe_report,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        temporary_path.replace(path)

    except OSError as error:
        temporary_path.unlink(
            missing_ok=True
        )

        raise OperationalReportError(
            f"Could not save report: {path}"
        ) from error

    return path