# syntax=docker/dockerfile:1
#
# Multi-role image for pdp-api / pdp-engine / pdp-ops (see pyproject.toml [project.scripts]
# and pdp/runtime/entrypoints.py). Role is selected at `docker run`/compose `command:` time —
# one image, three roles, per openspec/changes/api-worker-decoupling/design.md Phase 4.

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install deps first so dependency layers cache independently of app-code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY pdp ./pdp
COPY README.md ./
RUN uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm AS runtime
WORKDIR /app

# curl is required by the compose/ECS healthcheck (`curl -f http://localhost:$PORT/readyz`).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 pdp
COPY --from=builder --chown=pdp:pdp /app/.venv /app/.venv
COPY --from=builder --chown=pdp:pdp /app/pdp /app/pdp
COPY --from=builder --chown=pdp:pdp /app/pyproject.toml /app/README.md ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER pdp
EXPOSE 8000

# PDP_ROLE + command are set per-service in docker-compose.yml (api/engine/ops each run
# with a different console script, all sharing this one image).
CMD ["pdp-api"]
