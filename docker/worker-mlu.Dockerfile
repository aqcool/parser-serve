ARG MLU_BASE_IMAGE
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.19

FROM ${UV_IMAGE} AS uv
FROM ${MLU_BASE_IMAGE}

ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    PARSER_WORKER_DEVICE_RUNTIME=mlu PARSER_WORKER_DEVICE_VENDOR=cambricon \
    PARSER_WORKER_DEVICE_ID=mlu-0 PARSER_WORKER_DEVICE_MODEL="Configured Cambricon MLU"

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra worker-mlu --extra object-storage
COPY parser_serve ./parser_serve
RUN uv sync --frozen --no-dev --extra worker-mlu --extra object-storage \
    && mkdir -p /app/data && chown -R 10001:0 /app

USER 10001
CMD ["parser-worker"]
