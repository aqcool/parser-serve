"""API key authentication without storing plaintext keys."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable

from fastapi import Request
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from ..persistence import Database
from ..persistence.api_keys import ApiKeyRepository
from ..persistence.models import ApiKeyRecord
from ..schema.authentication import ApiKeyKind
from ..schema.error import ErrorCode
from .errors import ApiError


class ApiKeyAuthenticator:
    def __init__(self, api_keys: Iterable[SecretStr]) -> None:
        self._digests = tuple(
            self._digest(api_key.get_secret_value()) for api_key in api_keys
        )

    @staticmethod
    def _digest(api_key: str) -> bytes:
        return hashlib.sha256(api_key.encode("utf-8")).digest()

    def authenticate(self, candidate: str) -> bool:
        candidate_digest = self._digest(candidate)
        matched = False
        for expected_digest in self._digests:
            matched |= hmac.compare_digest(candidate_digest, expected_digest)
        return matched


def _extract_api_key(request: Request) -> str:
    authorization = request.headers.get("Authorization")
    header_api_key = request.headers.get("X-API-Key")

    bearer_api_key: str | None = None
    if authorization is not None:
        scheme, separator, credentials = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not credentials.strip():
            raise ApiError(
                status_code=401,
                code=ErrorCode.AUTHENTICATION_FAILED,
                message="Authorization must use the Bearer scheme",
            )
        bearer_api_key = credentials.strip()

    if (
        bearer_api_key is not None
        and header_api_key is not None
        and bearer_api_key != header_api_key
    ):
        raise ApiError(
            status_code=401,
            code=ErrorCode.AUTHENTICATION_FAILED,
            message="Authorization and X-API-Key credentials do not match",
        )

    api_key = bearer_api_key or header_api_key
    if api_key is None:
        raise ApiError(
            status_code=401,
            code=ErrorCode.AUTHENTICATION_FAILED,
            message="An API key is required",
        )
    return api_key


async def require_api_key(request: Request) -> None:
    api_key = _extract_api_key(request)
    authenticator: ApiKeyAuthenticator = request.app.state.api_key_authenticator
    if authenticator.authenticate(api_key):
        return
    if await _authenticate_database(
        request,
        api_key=api_key,
        kind=ApiKeyKind.ORDINARY,
    ):
        return
    raise _invalid_api_key()


async def require_worker_api_key(request: Request) -> None:
    api_key = _extract_api_key(request)
    authenticator: ApiKeyAuthenticator = request.app.state.worker_api_key_authenticator
    if authenticator.authenticate(api_key):
        request.state.authenticated_worker_id = None
        return
    record = await _authenticate_database(
        request,
        api_key=api_key,
        kind=ApiKeyKind.WORKER,
    )
    if record is not None:
        request.state.authenticated_worker_id = record.worker_id
        return
    raise _invalid_api_key()


async def _authenticate_database(
    request: Request,
    *,
    api_key: str,
    kind: ApiKeyKind,
) -> ApiKeyRecord | None:
    database: Database | None = request.app.state.database
    if database is not None:
        repository: ApiKeyRepository = request.app.state.api_key_repository
        try:
            async with database.session_factory() as session:
                record = await repository.authenticate(
                    session,
                    api_key=api_key,
                    now=request.app.state.clock(),
                    kind=kind,
                )
                await session.commit()
        except SQLAlchemyError as exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="The authentication database is unavailable",
                retryable=True,
            ) from exc
        if record is not None:
            return record
    return None


def _invalid_api_key() -> ApiError:
    return ApiError(
        status_code=401,
        code=ErrorCode.AUTHENTICATION_FAILED,
        message="The API key is invalid",
    )


__all__ = [
    "ApiKeyAuthenticator",
    "require_api_key",
    "require_worker_api_key",
]
