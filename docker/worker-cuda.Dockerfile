# Supply a vetted NVIDIA CUDA runtime image that also contains Python 3.12/3.13:
# docker build --build-arg CUDA_BASE_IMAGE=<vendor-image> ...
ARG CUDA_BASE_IMAGE
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.19

FROM ${UV_IMAGE} AS uv
FROM ${CUDA_BASE_IMAGE}

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PARSER_WORKER_DEVICE_RUNTIME=cuda \
    PARSER_WORKER_DEVICE_VENDOR=nvidia \
    PARSER_WORKER_DEVICE_PROBE_REQUIRED=true \
    PARSER_WORKER_DEVICE_ID=cuda-0 \
    PARSER_WORKER_DEVICE_MODEL="Configured NVIDIA GPU"

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project \
    --extra worker-cuda \
    --extra object-storage
COPY parser_serve ./parser_serve
RUN uv sync --frozen --no-dev \
    --extra worker-cuda \
    --extra object-storage \
    && mkdir -p /app/data \
    && chown -R 10001:0 /app

USER 10001
CMD ["parser-worker"]
