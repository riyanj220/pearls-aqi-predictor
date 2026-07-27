"""Route exports for the versioned FastAPI service."""

from app.api.routes.alerts import (
    router as alerts_router,
)
from app.api.routes.forecast import (
    router as forecast_router,
)
from app.api.routes.health import (
    router as health_router,
)
from app.api.routes.metadata import (
    router as metadata_router,
)

__all__ = [
    "alerts_router",
    "forecast_router",
    "health_router",
    "metadata_router",
]