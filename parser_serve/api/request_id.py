"""Request ID generation and propagation."""

from __future__ import annotations

import logging
import re
import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from ..observability import log_context

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^req_[a-zA-Z0-9_-]{8,64}$")


def request_id_for(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and _REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id
    generated = f"req_{uuid4().hex}"
    request.state.request_id = generated
    return generated


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request.state.request_id = (
            incoming
            if incoming is not None and _REQUEST_ID_PATTERN.fullmatch(incoming)
            else f"req_{uuid4().hex}"
        )
        logger = getattr(
            request.app.state,
            "logger",
            logging.getLogger("parser_serve.api"),
        )
        metrics = getattr(request.app.state, "metrics", None)
        started = time.perf_counter()
        status_code = 500
        with log_context(request_id=request.state.request_id):
            try:
                response = await call_next(request)
                status_code = response.status_code
                response.headers[REQUEST_ID_HEADER] = request.state.request_id
                return response
            finally:
                route_object = request.scope.get("route")
                route = getattr(route_object, "path", None) or "unmatched"
                duration = max(time.perf_counter() - started, 0.0)
                if metrics is not None:
                    metrics.observe_http(
                        method=request.method,
                        route=route,
                        status_code=status_code,
                        duration_seconds=duration,
                    )
                path_values = {
                    name: value
                    for name in ("task_id", "stage_id", "worker_id")
                    if isinstance(
                        (value := request.path_params.get(name)),
                        str,
                    )
                }
                authenticated_worker = getattr(
                    request.state,
                    "authenticated_worker_id",
                    None,
                )
                if "worker_id" not in path_values and isinstance(
                    authenticated_worker, str
                ):
                    path_values["worker_id"] = authenticated_worker
                logger.info(
                    "HTTP request completed",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "route": route,
                        "status_code": status_code,
                        "duration_ms": round(duration * 1000, 3),
                        **path_values,
                    },
                )


__all__ = ["REQUEST_ID_HEADER", "RequestIdMiddleware", "request_id_for"]
