"""Request ID and request-duration middleware."""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

LOGGER = logging.getLogger(__name__)


class RequestContextMiddleware(
    BaseHTTPMiddleware
):
    """Add request IDs and consistently log request duration."""

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        request_id = (
            request.headers.get(
                "X-Request-ID"
            )
            or str(uuid4())
        )

        request.state.request_id = request_id

        started_at = time.perf_counter()

        try:
            response = await call_next(
                request
            )
        except Exception:
            duration_ms = (
                time.perf_counter()
                - started_at
            ) * 1_000

            LOGGER.exception(
                (
                    "request_failed request_id=%s "
                    "method=%s route=%s "
                    "duration_ms=%.3f"
                ),
                request_id,
                request.method,
                request.url.path,
                duration_ms,
            )

            raise

        duration_ms = (
            time.perf_counter()
            - started_at
        ) * 1_000

        response.headers[
            "X-Request-ID"
        ] = request_id

        response.headers[
            "X-Process-Time-Ms"
        ] = f"{duration_ms:.3f}"

        LOGGER.info(
            (
                "request_completed request_id=%s "
                "method=%s route=%s status=%s "
                "duration_ms=%.3f"
            ),
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

        return response