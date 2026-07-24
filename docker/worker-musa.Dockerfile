ARG MUSA_BASE_IMAGE
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.19

FROM ${UV_IMAGE} AS uv
FROM ${MUSA_BASE_IMAGE}

ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    PARSER_WORKER_DEVICE_RUNTIME=musa PARSER_WORKER_DEVICE_VENDOR=moore_threads \
    PARSER_WORKER_DEVICE_ID=musa-0 PARSER_WORKER_DEVICE_MODEL="Configured MUSA GPU"

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra worker-musa --extra object-storage
COPY parser_serve ./parser_serve
RUN uv sync --frozen --no-dev --extra worker-musa --extra object-storage \
    && mkdir -p /app/data && chown -R 10001:0 /app

USER 10001
CMD ["parser-worker"]
