# Backward-compatible root build target. The canonical CPU Worker definition is
# docker/worker-cpu.Dockerfile; keep both files aligned.
ARG PYTHON_BASE_IMAGE=python:3.13-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.19

FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_BASE_IMAGE}

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PARSER_WORKER_DEVICE_RUNTIME=cpu \
    PARSER_WORKER_DEVICE_VENDOR=generic \
    PARSER_WORKER_SUBPROCESS_RESOURCE_LIMITS_REQUIRED=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-liberation \
        fonts-noto-cjk \
        libreoffice-calc \
        libreoffice-impress \
        libreoffice-writer \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project \
    --extra worker-cpu \
    --extra object-storage
COPY parser_serve ./parser_serve
RUN uv sync --frozen --no-dev \
    --extra worker-cpu \
    --extra object-storage \
    && mkdir -p /app/data \
    && chown -R 10001:0 /app

USER 10001
CMD ["parser-worker"]
