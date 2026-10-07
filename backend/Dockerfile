# syntax=docker/dockerfile:1.7
# One image for the API, both workers, migrations and the CLI; the command picks the role.
# Built for linux/amd64 and linux/arm64: production runs on an Ampere VM (ADR-0003 §5).
# Build context: the repository root.

ARG PYTHON_IMAGE=python:3.14-slim

FROM ghcr.io/astral-sh/uv:0.11.25 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
COPY backend/migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# Model weights ship inside the image; containers never download them (ADR-0003 §1).
COPY config ./config
RUN ESFAKE_CONFIG_DIR=/app/config ESFAKE_MODELS_DIR=/app/models \
    /app/.venv/bin/esfake download-models \
 && chmod -R a+rX /app/models

FROM ${PYTHON_IMAGE} AS runtime
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin esfake
WORKDIR /app
# Code and config stay root-owned and read-only for the service user.
COPY --from=build /app /app
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    ESFAKE_CONFIG_DIR=/app/config \
    ESFAKE_MODELS_DIR=/app/models \
    ESFAKE_MODELS_OFFLINE=true \
    HF_HUB_OFFLINE=1
USER esfake
EXPOSE 8000 8001
CMD ["esfake", "serve"]
