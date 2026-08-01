"""Structured JSON logging for services and batch pipelines."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Mapping


STANDARD_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}

SENSITIVE_FIELD_MARKERS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "connection_string",
    "storage_key",
    "credential",
}


class StructuredLoggingError(RuntimeError):
    """Raised when structured logging cannot be configured."""


def utc_timestamp() -> str:
    """Return the current UTC timestamp."""

    return datetime.now(
        timezone.utc
    ).isoformat()


def is_sensitive_field(
    name: str,
) -> bool:
    """Return whether a field name appears sensitive."""

    normalized = (
        name.strip()
        .lower()
        .replace("-", "_")
    )

    return any(
        marker in normalized
        for marker in SENSITIVE_FIELD_MARKERS
    )


def sanitize_value(
    name: str,
    value: Any,
) -> Any:
    """Redact sensitive values recursively."""

    if is_sensitive_field(name):
        return "[REDACTED]"

    if isinstance(value, Mapping):
        return {
            str(child_name): sanitize_value(
                str(child_name),
                child_value,
            )
            for child_name, child_value
            in value.items()
        }

    if isinstance(value, list):
        return [
            sanitize_value(
                name,
                child_value,
            )
            for child_value in value
        ]

    if isinstance(value, tuple):
        return [
            sanitize_value(
                name,
                child_value,
            )
            for child_value in value
        ]

    if isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
        ),
    ) or value is None:
        return value

    return str(value)


class JsonLogFormatter(logging.Formatter):
    """Convert logging records into one-line JSON."""

    def format(
        self,
        record: logging.LogRecord,
    ) -> str:
        """Format one log record."""

        payload: dict[str, Any] = {
            "timestamp_utc": utc_timestamp(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for name, value in record.__dict__.items():
            if name in STANDARD_LOG_RECORD_FIELDS:
                continue

            if name.startswith("_"):
                continue

            payload[name] = sanitize_value(
                name,
                value,
            )

        if record.exc_info is not None:
            payload["exception"] = (
                self.formatException(
                    record.exc_info
                )
            )

        return json.dumps(
            payload,
            default=str,
            separators=(",", ":"),
        )


def resolve_log_level(
    value: str | None,
) -> int:
    """Resolve a configured logging level."""

    normalized = (
        value or "INFO"
    ).strip().upper()

    resolved = getattr(
        logging,
        normalized,
        None,
    )

    if not isinstance(resolved, int):
        raise StructuredLoggingError(
            f"Unsupported log level: {normalized}"
        )

    return resolved


def configure_structured_logging(
    *,
    service_name: str,
    environment: str | None = None,
    log_level: str | None = None,
) -> logging.Logger:
    """Configure and return the root application logger."""

    if not service_name.strip():
        raise StructuredLoggingError(
            "service_name cannot be empty."
        )

    resolved_environment = (
        environment
        or os.getenv(
            "APP_ENV",
            "development",
        )
    )

    resolved_log_level = (
        log_level
        or os.getenv(
            "LOG_LEVEL",
            "INFO",
        )
    )

    handler = logging.StreamHandler(
        sys.stdout
    )

    handler.setFormatter(
        JsonLogFormatter()
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(
        resolve_log_level(
            resolved_log_level
        )
    )

    logger = logging.getLogger(
        service_name
    )

    logger.info(
        "Structured logging configured.",
        extra={
            "event": (
                "logging_configured"
            ),
            "service_name": service_name,
            "environment": (
                resolved_environment
            ),
        },
    )

    return logger


def get_logger(
    name: str,
) -> logging.Logger:
    """Return one named logger."""

    return logging.getLogger(name)


def log_pipeline_started(
    logger: logging.Logger,
    *,
    pipeline_name: str,
    pipeline_run_id: str,
    service_name: str = "pipeline",
) -> None:
    """Log pipeline execution start."""

    logger.info(
        "Pipeline started.",
        extra={
            "event": "pipeline_started",
            "service_name": service_name,
            "pipeline_name": pipeline_name,
            "pipeline_run_id": (
                pipeline_run_id
            ),
            "status": "STARTED",
        },
    )


def log_pipeline_completed(
    logger: logging.Logger,
    *,
    pipeline_name: str,
    pipeline_run_id: str,
    duration_seconds: float,
    row_count: int | None = None,
    model_version: str | int | None = None,
) -> None:
    """Log successful pipeline completion."""

    logger.info(
        "Pipeline completed.",
        extra={
            "event": "pipeline_completed",
            "service_name": "pipeline",
            "pipeline_name": pipeline_name,
            "pipeline_run_id": (
                pipeline_run_id
            ),
            "status": "COMPLETED",
            "duration_seconds": round(
                duration_seconds,
                3,
            ),
            "row_count": row_count,
            "model_version": model_version,
        },
    )


def log_pipeline_failed(
    logger: logging.Logger,
    *,
    pipeline_name: str,
    pipeline_run_id: str,
    error_code: str,
    error: Exception,
    duration_seconds: float | None = None,
) -> None:
    """Log pipeline failure without exposing secrets."""

    logger.error(
        "Pipeline failed.",
        exc_info=True,
        extra={
            "event": "pipeline_failed",
            "service_name": "pipeline",
            "pipeline_name": pipeline_name,
            "pipeline_run_id": (
                pipeline_run_id
            ),
            "status": "FAILED",
            "error_code": error_code,
            "error_type": type(
                error
            ).__name__,
            "duration_seconds": (
                round(
                    duration_seconds,
                    3,
                )
                if duration_seconds
                is not None
                else None
            ),
        },
    )