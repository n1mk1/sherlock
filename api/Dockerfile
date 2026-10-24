# One image serves the API and the built web app from one origin (TRD §11).
# Build from the repo root:  docker build -f api/Dockerfile -t sherlock .

# --- Stage 1: the web app -----------------------------------------------------
FROM node:24-bookworm-slim AS web
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# --- Stage 2: the API ---------------------------------------------------------
FROM python:3.12-slim-bookworm AS api
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1

WORKDIR /app/api
COPY api/pyproject.toml api/uv.lock api/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY api/sherlock ./sherlock
RUN uv sync --frozen --no-dev

COPY --from=web /web/dist /app/web

# `app` runs the API; `sandbox` will run cleaning workers (TRD §3.4, Implementation Plan D2.4).
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app \
 && useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin sandbox

COPY api/docker/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

ENV PATH=/opt/venv/bin:$PATH \
    DATA_DIR=/data \
    DATABASE_URL=sqlite:////data/sherlock.db \
    WEB_DIST_DIR=/app/web

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "sherlock.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
