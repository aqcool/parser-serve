ARG PYTHON_BASE_IMAGE=python:3.13-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.19

FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_BASE_IMAGE}

ARG BUILD_COMMIT=""
ARG BUILD_TIME=""

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PARSER_SERVE_BUILD_COMMIT=${BUILD_COMMIT} \
    PARSER_SERVE_BUILD_TIME=${BUILD_TIME}

LABEL org.opencontainers.image.revision="${BUILD_COMMIT}" \
      org.opencontainers.image.created="${BUILD_TIME}"

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra control-plane
COPY alembic.ini ./
COPY migrations ./migrations
COPY parser_serve ./parser_serve
RUN uv sync --frozen --no-dev --extra control-plane \
    && mkdir -p /app/data/storage \
    && chown -R 10001:0 /app

USER 10001
EXPOSE 8000
CMD ["uvicorn", "parser_serve.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
