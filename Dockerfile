# syntax=docker/dockerfile:1

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 \
    /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN addgroup --system api \
    && adduser --system --ingroup api api

# Install only the core FastAPI runtime dependencies.
COPY pyproject.toml uv.lock ./

RUN uv sync \
    --locked \
    --no-default-groups \
    --no-install-project

# Copy runtime files with their final ownership.
COPY --chown=api:api app ./app
COPY --chown=api:api aqi/latest ./aqi/latest

USER api

EXPOSE 8000

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=20s \
    --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/live', timeout=3)"

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]