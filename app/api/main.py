"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import (
    CORSMiddleware,
)
from fastapi.middleware.gzip import (
    GZipMiddleware,
)

from app.api.config import (
    APISettings,
    get_api_settings,
)
from app.api.errors import (
    register_exception_handlers,
)
from app.api.middleware import (
    RequestContextMiddleware,
)
from app.api.routes import (
    alerts_router,
    forecast_router,
    health_router,
    metadata_router,
)
from app.api.services.artifact_repository import (
    ArtifactRepository,
    ArtifactRepositoryError,
)

LOGGER = logging.getLogger(__name__)


def configure_logging(
    settings: APISettings,
) -> None:
    """Configure consistent application logging."""

    logging.basicConfig(
        level=getattr(
            logging,
            settings.log_level,
        ),
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(name)s "
            "%(message)s"
        ),
    )


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""

    settings = get_api_settings()

    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        repository = ArtifactRepository(
            settings
        )

        app.state.artifact_repository = (
            repository
        )

        app.state.forecast_ready = False

        try:
            bundle = repository.load_latest(
                force_reload=True
            )

            app.state.forecast_ready = True

            LOGGER.info(
                (
                    "artifact_cache_warmed "
                    "phase_6_run_id=%s "
                    "forecast_rows=%s"
                ),
                bundle.phase_6_run_id,
                len(bundle.forecast_df),
            )

        except ArtifactRepositoryError:
            LOGGER.exception(
                (
                    "artifact_cache_warm_failed "
                    "service_will_start_not_ready"
                )
            )

        yield

        repository.clear_cache()

    app = FastAPI(
        title=settings.application_name,
        description=(
            settings.application_description
        ),
        version=(
            settings.application_version
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        contact={
            "name": "Pearls AQI Predictor",
        },
        license_info={
            "name": (
                "Project demonstration service"
            ),
        },
    )

    app.add_middleware(
        RequestContextMiddleware
    )

    app.add_middleware(
        GZipMiddleware,
        minimum_size=1_000,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(
            settings.allowed_cors_origins
        ),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "X-Request-ID",
        ],
        expose_headers=[
            "X-Request-ID",
            "X-Process-Time-Ms",
        ],
    )

    register_exception_handlers(app)

    app.include_router(
        health_router,
        prefix=settings.api_prefix,
    )

    app.include_router(
        forecast_router,
        prefix=settings.api_prefix,
    )

    app.include_router(
        alerts_router,
        prefix=settings.api_prefix,
    )

    app.include_router(
        metadata_router,
        prefix=settings.api_prefix,
    )

    @app.get(
        "/",
        include_in_schema=False,
    )
    def root() -> dict[str, str]:
        """Provide a small service-discovery response."""

        return {
            "service": (
                settings.application_name
            ),
            "version": (
                settings.application_version
            ),
            "documentation": "/docs",
            "api_prefix": (
                settings.api_prefix
            ),
        }

    return app


app = create_application()