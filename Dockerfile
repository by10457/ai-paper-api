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
    && /app/.venv/bin/python -c "import docx, fastapi, langchain_openai, matplotlib, numpy, PIL, qiniu, redis, tortoise, uvicorn"


FROM python:${PYTHON_VERSION}-slim AS runtime

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    APP_DEBUG=false \
    APP_HOST=0.0.0.0 \
    APP_PORT=10462 \
    HOME=/home/app \
    XDG_CONFIG_HOME=/home/app/.config \
    XDG_CACHE_HOME=/home/app/.cache \
    MPLCONFIGDIR=/home/app/.config/matplotlib \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    LOG_FILE=logs/app.log \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        fonts-noto-cjk \
        fonts-wqy-zenhei \
        nodejs \
        npm \
    && npm install -g @mermaid-js/mermaid-cli \
    && fc-cache -f \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/logs /app/public/output/thesis /home/app/.config/matplotlib /home/app/.cache/dconf \
    && chown -R app:app /app /home/app

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

EXPOSE 10462

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.getenv('APP_PORT', '10462'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=3)" || exit 1

USER app

CMD ["python", "main.py"]
