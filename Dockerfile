ARG PYTHON_VERSION=3.13
ARG RUNTIME_BASE_IMAGE=localhost/ai-paper-api:runtime-base
ARG MERMAID_CLI_VERSION=10.9.1
ARG UV_VERSION=0.8.15
ARG PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PYPI_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

FROM python:${PYTHON_VERSION}-slim AS deps-builder

ARG PYPI_INDEX_URL
ARG PYPI_TRUSTED_HOST
ARG UV_VERSION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_HTTP_TIMEOUT=120 \
    PIP_INDEX_URL=${PYPI_INDEX_URL} \
    PIP_TRUSTED_HOST=${PYPI_TRUSTED_HOST} \
    UV_DEFAULT_INDEX=${PYPI_INDEX_URL} \
    UV_INDEX_URL=${PYPI_INDEX_URL}

WORKDIR /app

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

# 先复制依赖文件，依赖不变时可复用 Docker layer。
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project --default-index "${PYPI_INDEX_URL}" \
    && /app/.venv/bin/python -c "import docx, fastapi, langchain_openai, matplotlib, numpy, PIL, qiniu, redis, tortoise, uvicorn"


FROM python:${PYTHON_VERSION}-slim AS runtime-base

ARG APT_MIRROR=https://mirrors.tencent.com/debian
ARG APT_SECURITY_MIRROR=https://mirrors.tencent.com/debian-security
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG MERMAID_CLI_VERSION
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
    PUPPETEER_SKIP_DOWNLOAD=true \
    LOG_FILE=logs/app.log \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN set -eux; \
    for file in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
        if [ -f "$file" ]; then \
            sed -i \
                -e "s|http://deb.debian.org/debian|${APT_MIRROR}|g" \
                -e "s|https://deb.debian.org/debian|${APT_MIRROR}|g" \
                -e "s|http://security.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
                -e "s|https://security.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
                -e "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
                -e "s|https://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
                "$file"; \
        fi; \
    done; \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        fonts-noto-cjk \
        fonts-wqy-zenhei \
        nodejs \
        npm \
    && npm config set registry "${NPM_REGISTRY}" \
    && npm install -g "@mermaid-js/mermaid-cli@${MERMAID_CLI_VERSION}" --registry "${NPM_REGISTRY}" \
    && node --version \
    && npm --version \
    && chromium --version \
    && mmdc --version \
    && fc-cache -f \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/logs /app/public/output/thesis /home/app/.config/matplotlib /home/app/.cache/dconf \
    && chown -R app:app /app /home/app

COPY --from=deps-builder --chown=app:app /app/.venv /app/.venv

EXPOSE 10462

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.getenv('APP_PORT', '10462'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=3)" || exit 1


FROM runtime-base AS app

COPY --chown=app:app main.py app.py ./
COPY --chown=app:app api ./api
COPY --chown=app:app core ./core
COPY --chown=app:app llm ./llm
COPY --chown=app:app models ./models
COPY --chown=app:app schemas ./schemas
COPY --chown=app:app services ./services
COPY --chown=app:app tasks ./tasks
COPY --chown=app:app utils ./utils
COPY --chown=app:app public ./public
COPY --chown=app:app sql ./sql

USER app

CMD ["python", "main.py"]


FROM ${RUNTIME_BASE_IMAGE} AS app-fast

COPY --chown=app:app main.py app.py ./
COPY --chown=app:app api ./api
COPY --chown=app:app core ./core
COPY --chown=app:app llm ./llm
COPY --chown=app:app models ./models
COPY --chown=app:app schemas ./schemas
COPY --chown=app:app services ./services
COPY --chown=app:app tasks ./tasks
COPY --chown=app:app utils ./utils
COPY --chown=app:app public ./public
COPY --chown=app:app sql ./sql

USER app

CMD ["python", "main.py"]
