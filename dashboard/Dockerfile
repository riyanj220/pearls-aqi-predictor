# syntax=docker/dockerfile:1

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 \
    /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN addgroup --system dashboard \
    && adduser --system \
    --ingroup dashboard \
    dashboard

COPY pyproject.toml uv.lock ./

RUN uv sync \
    --locked \
    --only-group dashboard

COPY --chown=dashboard:dashboard \
    dashboard ./dashboard

COPY --chown=dashboard:dashboard \
    .streamlit ./.streamlit

USER dashboard

EXPOSE 8501

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=20s \
    --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=3)"

CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]