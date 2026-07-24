"""Ordinary API Key authentication for the MCP ASGI transport."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..api.authentication import ApiKeyAuthenticator
from ..persistence import Database
from ..persistence.api_keys import ApiKeyRepository
from ..schema.authentication import ApiKeyKind


Clock = Callable[[], datetime]


class McpApiKeyMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        authenticator: ApiKeyAuthenticator,
        database: Database,
        repository: ApiKeyRepository,
        clock: Clock,
    ) -> None:
        self.app = app
        self.authenticator = authenticator
        self.database = database
        self.repository = repository
        self.clock = clock

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").casefold(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        candidate = self._candidate(headers)
        if candidate is None or not await self._authenticate(candidate):
            await self._response(
                401, "An ordinary API key is required", scope, receive, send
            )
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _candidate(headers: dict[str, str]) -> str | None:
        authorization = headers.get("authorization")
        header_key = headers.get("x-api-key")
        bearer: str | None = None
        if authorization is not None:
            scheme, separator, credential = authorization.partition(" ")
            if separator and scheme.casefold() == "bearer" and credential.strip():
                bearer = credential.strip()
            else:
                return None
        if bearer is not None and header_key is not None and bearer != header_key:
            return None
        return bearer or header_key

    async def _authenticate(self, candidate: str) -> bool:
        if self.authenticator.authenticate(candidate):
            return True
        try:
            async with self.database.session_factory() as session:
                record = await self.repository.authenticate(
                    session,
                    api_key=candidate,
                    now=self.clock(),
                    kind=ApiKeyKind.ORDINARY,
                )
                await session.commit()
        except SQLAlchemyError:
            return False
        return record is not None

    @staticmethod
    async def _response(
        status_code: int,
        message: str,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        response = JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32001,
                    "message": message,
                },
                "id": None,
            },
            status_code=status_code,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)


__all__ = ["McpApiKeyMiddleware"]
