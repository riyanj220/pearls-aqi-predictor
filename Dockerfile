# syntax=docker/dockerfile:1

FROM python:3.12-slim

# Copy the uv binaries from the official uv image.
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Create a non-root runtime user.
RUN addgroup --system api \
    && adduser --system --ingroup api api

# Copy dependency metadata first for better Docker layer caching.
COPY pyproject.toml uv.lock ./

# Install production dependencies exactly as locked.
# The application source is copied afterward.
RUN uv sync \
    --locked \
    --no-dev \
    --no-install-project

# Copy the FastAPI application.
COPY app ./app

# Copy the Phase 6 artifacts required by the API.
# Keep this only when the artifacts should be included in the image.
COPY aqi/latest ./aqi/latest

# Ensure the non-root user can read the application and artifacts.
RUN chown -R api:api /app

USER api

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]