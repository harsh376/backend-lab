# syntax=docker/dockerfile:1

FROM python:3.13-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.7-python3.13-bookworm-slim /usr/local/bin/uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1
RUN useradd --create-home --shell /usr/sbin/nologin appuser
WORKDIR /app

FROM base AS deps
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

FROM deps AS app
ARG GIT_COMMIT_SHA
ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}
COPY pyproject.toml uv.lock ./
COPY apps/__init__.py ./apps/__init__.py
COPY apps/mcp ./apps/mcp
COPY apps/evals ./apps/evals
COPY backend ./backend
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"
USER appuser

CMD ["python", "-m", "apps.mcp.agent.worker"]
