"""Structured API exceptions and exception handlers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.services.artifact_repository import (
    ArtifactFormatError,
    ArtifactNotFoundError,
    ArtifactRepositoryError,
    ArtifactRunMismatchError,
    ArtifactSchemaError,
)

from starlette.exceptions import (
    HTTPException as StarletteHTTPException,
)

LOGGER = logging.getLogger(__name__)


class APIServiceError(Exception):
    """Public-safe service exception."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)

        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def _request_id(request: Request) -> str:
    """Read the request ID assigned by middleware."""

    return str(
        getattr(
            request.state,
            "request_id",
            "unknown",
        )
    )


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Create the standard API error response."""

    request_id = _request_id(request)

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id,
                "timestamp_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        },
        headers={
            "X-Request-ID": request_id,
        },
    )


async def api_service_error_handler(
    request: Request,
    exc: APIServiceError,
) -> JSONResponse:
    """Handle expected public service errors."""

    LOGGER.warning(
        "API service error code=%s request_id=%s message=%s",
        exc.code,
        _request_id(request),
        exc.message,
    )

    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def artifact_error_handler(
    request: Request,
    exc: ArtifactRepositoryError,
) -> JSONResponse:
    """Convert repository errors into structured 503 responses."""

    if isinstance(exc, ArtifactNotFoundError):
        code = "FORECAST_NOT_FOUND"
        message = (
            "The latest forecast artifacts are not available."
        )

    elif isinstance(exc, ArtifactRunMismatchError):
        code = "ARTIFACT_RUN_MISMATCH"
        message = (
            "The latest forecast artifacts belong to "
            "different pipeline runs."
        )

    elif isinstance(
        exc,
        (
            ArtifactSchemaError,
            ArtifactFormatError,
        ),
    ):
        code = "ARTIFACT_SCHEMA_INVALID"
        message = (
            "The latest forecast artifacts are invalid."
        )

    else:
        code = "FORECAST_NOT_READY"
        message = (
            "The latest validated forecast is not ready."
        )

    LOGGER.exception(
        "Artifact repository failure code=%s request_id=%s",
        code,
        _request_id(request),
    )

    return _error_response(
        request=request,
        status_code=503,
        code=code,
        message=message,
    )


async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return a consistent response for invalid query parameters."""

    safe_errors = [
        {
            "location": list(error.get("loc", [])),
            "message": error.get(
                "msg",
                "Invalid request value.",
            ),
            "type": error.get(
                "type",
                "validation_error",
            ),
        }
        for error in exc.errors()
    ]

    return _error_response(
        request=request,
        status_code=422,
        code="INVALID_QUERY_PARAMETER",
        message=(
            "One or more request parameters are invalid."
        ),
        details={
            "validation_errors": safe_errors,
        },
    )

async def http_exception_error_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Convert framework HTTP errors into the standard response."""

    if exc.status_code == 404:
        code = "RESOURCE_NOT_FOUND"
        message = "The requested API resource was not found."
    elif exc.status_code == 405:
        code = "METHOD_NOT_ALLOWED"
        message = (
            "The requested HTTP method is not allowed "
            "for this resource."
        )
    else:
        code = "HTTP_ERROR"
        message = str(
            exc.detail
            or "The request could not be completed."
        )

    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=code,
        message=message,
    )

async def unexpected_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Hide internal implementation details from clients."""

    LOGGER.exception(
        "Unexpected API failure request_id=%s",
        _request_id(request),
    )

    return _error_response(
        request=request,
        status_code=500,
        code="INTERNAL_SERVICE_ERROR",
        message=(
            "An unexpected internal service error occurred."
        ),
    )


def register_exception_handlers(
    app: FastAPI,
) -> None:
    """Register all Phase 7 exception handlers."""

    app.add_exception_handler(
        APIServiceError,
        api_service_error_handler,
    )

    app.add_exception_handler(
        ArtifactRepositoryError,
        artifact_error_handler,
    )

    app.add_exception_handler(
        RequestValidationError,
        request_validation_error_handler,
    )

    app.add_exception_handler(
            StarletteHTTPException,
            http_exception_error_handler,
        )

    app.add_exception_handler(
        Exception,
        unexpected_error_handler,
    )
