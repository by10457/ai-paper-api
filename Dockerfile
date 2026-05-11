# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_HTTP_TIMEOUT=120

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /uvx /bin/

WORKDIR /app

# 先复制依赖文件，提升 Docker layer 缓存命中率。
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project \
    && /app/.venv/bin/python -c "import fastapi, uvicorn, tortoise, redis"


FROM python:${PYTHON_VERSION}-slim AS runtime

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    APP_DEBUG=false \
    APP_HOST=0.0.0.0 \
    APP_PORT=10457 \
    LOG_FILE=logs/app.log \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/logs /app/public \
    && chown -R app:app /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app main.py app.py ./
COPY --chown=app:app api ./api
COPY --chown=app:app core ./core
COPY --chown=app:app models ./models
COPY --chown=app:app schemas ./schemas
COPY --chown=app:app services ./services
COPY --chown=app:app tasks ./tasks
COPY --chown=app:app utils ./utils
COPY --chown=app:app public ./public
COPY --chown=app:app sql ./sql

EXPOSE 10457

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.getenv('APP_PORT', '10457'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=3)" || exit 1

USER app

CMD ["python", "main.py"]
