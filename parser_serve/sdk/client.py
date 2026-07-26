"""Typed synchronous and asynchronous clients for the Parser Serve HTTP API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime
from enum import Enum
from typing import Any, BinaryIO, TypeVar, cast
from urllib.parse import quote

import httpx
from pydantic import Field, TypeAdapter, ValidationError, field_validator

from ..schema.base import JsonValue, StrictSchema
from ..schema.common import (
    HealthData,
    HealthResponse,
    NonEmptyStr,
    RequestId,
    StrictBool,
)
from ..schema.error import ErrorCode, FieldViolation
from ..schema.file import UploadedFileDetail, UploadedFileResponse
from ..schema.result import ParseResult, ParseResultResponse
from ..schema.task import (
    CreateTaskData,
    CreateTaskRequest,
    CreateTaskResponse,
    TaskDetail,
    TaskDetailResponse,
    TaskListQuery,
    TaskListResponse,
)
from .generated import (
    OPERATION_SPECS,
    GeneratedAsyncClientMixin,
    GeneratedSyncClientMixin,
    OperationId,
)


ResponseT = TypeVar("ResponseT")
Scalar = str | int | float | bool | date | datetime | Enum
QueryValue = Scalar | Sequence[Scalar] | None
UploadContent = bytes | BinaryIO
UploadFile = tuple[str, UploadContent, str]


class SdkErrorDetail(StrictSchema):
    """Forward-compatible error payload returned by a newer service."""

    code: ErrorCode | NonEmptyStr
    message: NonEmptyStr
    retryable: StrictBool = False
    field_violations: list[FieldViolation] = Field(default_factory=list)
    context: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("code")
    @classmethod
    def normalize_known_code(cls, value: ErrorCode | str) -> ErrorCode | str:
        if isinstance(value, ErrorCode):
            return value
        try:
            return ErrorCode(value)
        except ValueError:
            return value


class SdkErrorResponse(StrictSchema):
    request_id: RequestId
    error: SdkErrorDetail


_ERROR_ADAPTER = TypeAdapter(SdkErrorResponse)
_HEALTH_ADAPTER = TypeAdapter(HealthResponse)
_CREATE_TASK_ADAPTER = TypeAdapter(CreateTaskResponse)
_TASK_DETAIL_ADAPTER = TypeAdapter(TaskDetailResponse)
_TASK_LIST_ADAPTER = TypeAdapter(TaskListResponse)
_RESULT_ADAPTER = TypeAdapter(ParseResultResponse)
_UPLOAD_ADAPTER = TypeAdapter(UploadedFileResponse)


class ParserServeApiError(Exception):
    """A non-success HTTP response, including its typed service error when present."""

    def __init__(
        self,
        *,
        status_code: int,
        response: SdkErrorResponse | None,
        fallback_message: str,
    ) -> None:
        self.status_code = status_code
        self.response = response
        self.detail: SdkErrorDetail | None = response.error if response else None
        self.request_id = response.request_id if response else None
        message = self.detail.message if self.detail else fallback_message
        super().__init__(f"Parser Serve returned HTTP {status_code}: {message}")

    @property
    def code(self) -> ErrorCode | str | None:
        return self.detail.code if self.detail else None

    @property
    def retryable(self) -> bool:
        return self.detail.retryable if self.detail else False


def _scalar(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _query_items(
    query: Mapping[str, QueryValue] | StrictSchema | None,
) -> tuple[tuple[str, str], ...]:
    if query is None:
        return ()
    values = (
        query.model_dump(mode="python", exclude_none=True)
        if isinstance(query, StrictSchema)
        else query
    )
    items: list[tuple[str, str]] = []
    for name, value in values.items():
        if value is None:
            continue
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            items.extend(
                (name, _scalar(item))
                for item in value
                if not isinstance(item, (bytes, bytearray))
            )
        else:
            items.append((name, _scalar(value)))
    return tuple(items)


def _request_parts(
    operation_id: OperationId,
    *,
    api_key: str,
    path: Mapping[str, Scalar] | None,
    query: Mapping[str, QueryValue] | StrictSchema | None,
    headers: Mapping[str, str] | None,
) -> tuple[str, str, tuple[tuple[str, str], ...], dict[str, str]]:
    operation = OPERATION_SPECS[operation_id]
    resolved_path = operation.path
    for name, value in (path or {}).items():
        resolved_path = resolved_path.replace(
            "{" + name + "}", quote(str(_scalar(value)), safe="")
        )
    if "{" in resolved_path or "}" in resolved_path:
        raise ValueError(f"missing path parameter for {operation_id}: {resolved_path}")
    request_headers = dict(headers or {})
    for name in request_headers:
        if name.lower() == "authorization":
            raise ValueError("Authorization is managed by the SDK")
    request_headers["Authorization"] = f"Bearer {api_key}"
    return operation.method, resolved_path, _query_items(query), request_headers


def _json_body(body: StrictSchema | object | None) -> object | None:
    if isinstance(body, StrictSchema):
        return body.model_dump(mode="json")
    return body


def _generated_values(
    *,
    path: object,
    query: object,
    headers: object,
    body: object,
    body_media_type: str | None,
) -> tuple[
    Mapping[str, Scalar] | None,
    Mapping[str, QueryValue] | StrictSchema | None,
    Mapping[str, str] | None,
    object | None,
    Mapping[str, UploadFile] | None,
    Mapping[str, str] | None,
]:
    multipart = (
        cast("Mapping[str, object]", body)
        if body_media_type == "multipart/form-data"
        else {}
    )
    return (
        cast("Mapping[str, Scalar] | None", path),
        cast("Mapping[str, QueryValue] | StrictSchema | None", query),
        cast("Mapping[str, str] | None", headers),
        None if body_media_type == "multipart/form-data" else body,
        (
            {
                name: cast("UploadFile", value)
                for name, value in multipart.items()
                if isinstance(value, tuple) and len(value) == 3
            }
            if body_media_type == "multipart/form-data"
            else None
        ),
        (
            {
                name: _scalar(value)
                for name, value in multipart.items()
                if not (isinstance(value, tuple) and len(value) == 3)
            }
            if body_media_type == "multipart/form-data"
            else None
        ),
    )


def _api_error(response: httpx.Response) -> ParserServeApiError:
    parsed: SdkErrorResponse | None = None
    try:
        parsed = _ERROR_ADAPTER.validate_json(response.content)
    except (ValidationError, ValueError):
        pass
    return ParserServeApiError(
        status_code=response.status_code,
        response=parsed,
        fallback_message=response.reason_phrase or "unexpected response",
    )


class ParserServeClient(GeneratedSyncClientMixin):
    """Blocking SDK client. It can own or reuse an existing ``httpx.Client``."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float | httpx.Timeout = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ParserServeClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _generated_json(
        self,
        operation_id: OperationId,
        *,
        path: object,
        query: object,
        headers: object,
        body: object,
        body_media_type: str | None,
        response_type: object,
    ) -> object:
        path_values, query_values, header_values, json_body, files, form = (
            _generated_values(
                path=path,
                query=query,
                headers=headers,
                body=body,
                body_media_type=body_media_type,
            )
        )
        return self.request(
            operation_id,
            TypeAdapter(cast(Any, response_type)),
            path=path_values,
            query=query_values,
            headers=header_values,
            body=json_body,
            files=files,
            form=form,
        )

    def _generated_bytes(
        self,
        operation_id: OperationId,
        *,
        path: object,
        query: object,
        headers: object,
        body: object,
        body_media_type: str | None,
    ) -> bytes:
        path_values, query_values, header_values, json_body, files, form = (
            _generated_values(
                path=path,
                query=query,
                headers=headers,
                body=body,
                body_media_type=body_media_type,
            )
        )
        return self.request_raw(
            operation_id,
            path=path_values,
            query=query_values,
            headers=header_values,
            body=json_body,
            files=files,
            form=form,
        ).content

    def _generated_text(
        self,
        operation_id: OperationId,
        *,
        path: object,
        query: object,
        headers: object,
        body: object,
        body_media_type: str | None,
    ) -> str:
        path_values, query_values, header_values, json_body, files, form = (
            _generated_values(
                path=path,
                query=query,
                headers=headers,
                body=body,
                body_media_type=body_media_type,
            )
        )
        return self.request_raw(
            operation_id,
            path=path_values,
            query=query_values,
            headers=header_values,
            body=json_body,
            files=files,
            form=form,
        ).text

    def _generated_stream(
        self,
        operation_id: OperationId,
        *,
        path: object,
        query: object,
        headers: object,
        body: object,
        body_media_type: str | None,
    ) -> Iterator[bytes]:
        path_values, query_values, header_values, _, _, _ = _generated_values(
            path=path,
            query=query,
            headers=headers,
            body=body,
            body_media_type=body_media_type,
        )
        with self.stream(
            operation_id,
            path=path_values,
            query=query_values,
            headers=header_values,
        ) as response:
            yield from response.iter_bytes()

    def _generated_none(
        self,
        operation_id: OperationId,
        *,
        path: object,
        query: object,
        headers: object,
        body: object,
        body_media_type: str | None,
    ) -> None:
        self._generated_bytes(
            operation_id,
            path=path,
            query=query,
            headers=headers,
            body=body,
            body_media_type=body_media_type,
        )

    def request_raw(
        self,
        operation_id: OperationId,
        *,
        path: Mapping[str, Scalar] | None = None,
        query: Mapping[str, QueryValue] | StrictSchema | None = None,
        headers: Mapping[str, str] | None = None,
        body: StrictSchema | object | None = None,
        files: Mapping[str, UploadFile] | None = None,
        form: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        method, url, params, request_headers = _request_parts(
            operation_id,
            api_key=self._api_key,
            path=path,
            query=query,
            headers=headers,
        )
        response = self._client.request(
            method,
            url,
            params=params,
            headers=request_headers,
            json=_json_body(body) if files is None else None,
            data=form,
            files=tuple(files.items()) if files is not None else None,
        )
        if not response.is_success:
            raise _api_error(response)
        return response

    def request(
        self,
        operation_id: OperationId,
        response_type: TypeAdapter[ResponseT] | type[ResponseT],
        *,
        path: Mapping[str, Scalar] | None = None,
        query: Mapping[str, QueryValue] | StrictSchema | None = None,
        headers: Mapping[str, str] | None = None,
        body: StrictSchema | object | None = None,
        files: Mapping[str, UploadFile] | None = None,
        form: Mapping[str, str] | None = None,
    ) -> ResponseT:
        response = self.request_raw(
            operation_id,
            path=path,
            query=query,
            headers=headers,
            body=body,
            files=files,
            form=form,
        )
        adapter = (
            response_type
            if isinstance(response_type, TypeAdapter)
            else TypeAdapter(response_type)
        )
        return adapter.validate_json(response.content)

    @contextmanager
    def stream(
        self,
        operation_id: OperationId,
        *,
        path: Mapping[str, Scalar] | None = None,
        query: Mapping[str, QueryValue] | StrictSchema | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[httpx.Response]:
        method, url, params, request_headers = _request_parts(
            operation_id,
            api_key=self._api_key,
            path=path,
            query=query,
            headers=headers,
        )
        with self._client.stream(
            method, url, params=params, headers=request_headers
        ) as response:
            if not response.is_success:
                response.read()
                raise _api_error(response)
            yield response

    def health(self) -> HealthData:
        return self.request("get_health", _HEALTH_ADAPTER).data

    def create_task(
        self, request: CreateTaskRequest, *, idempotency_key: str | None = None
    ) -> CreateTaskData:
        headers = (
            {"Idempotency-Key": idempotency_key}
            if idempotency_key is not None
            else None
        )
        return self.request(
            "create_task", _CREATE_TASK_ADAPTER, headers=headers, body=request
        ).data

    def get_task(self, task_id: str) -> TaskDetail:
        return self.request(
            "get_task", _TASK_DETAIL_ADAPTER, path={"task_id": task_id}
        ).data

    def list_tasks(self, query: TaskListQuery | None = None) -> TaskListResponse:
        return self.request("list_tasks", _TASK_LIST_ADAPTER, query=query)

    def get_result(self, task_id: str) -> ParseResult:
        return self.request(
            "get_task_result", _RESULT_ADAPTER, path={"task_id": task_id}
        ).data

    def upload_file(
        self, filename: str, content: UploadContent, mime_type: str
    ) -> UploadedFileDetail:
        return self.request(
            "upload_file",
            _UPLOAD_ADAPTER,
            files={"file": (filename, content, mime_type)},
        ).data

    def download_artifact(self, task_id: str, artifact_id: str) -> bytes:
        return self.request_raw(
            "download_task_artifact",
            path={"task_id": task_id, "artifact_id": artifact_id},
        ).content


class AsyncParserServeClient(GeneratedAsyncClientMixin):
    """Async SDK client. It can own or reuse an existing ``httpx.AsyncClient``."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float | httpx.Timeout = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncParserServeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def _generated_json(
        self,
        operation_id: OperationId,
        *,
        path: object,
        query: object,
        headers: object,
        body: object,
        body_media_type: str | None,
        response_type: object,
    ) -> object:
        path_values, query_values, header_values, json_body, files, form = (
            _generated_values(
                path=path,
                query=query,
                headers=headers,
                body=body,
                body_media_type=body_media_type,
            )
        )
        return await self.request(
            operation_id,
            TypeAdapter(cast(Any, response_type)),
            path=path_values,
            query=query_values,
            headers=header_values,
            body=json_body,
            files=files,
            form=form,
        )

    async def _generated_bytes(
        self,
        operation_id: OperationId,
        *,
        path: object,
        query: object,
        headers: object,
        body: object,
        body_media_type: str | None,
    ) -> bytes:
        path_values, query_values, header_values, json_body, files, form = (
            _generated_values(
                path=path,
                query=query,
                headers=headers,
                body=body,
                body_media_type=body_media_type,
            )
        )
        return (
            await self.request_raw(
                operation_id,
                path=path_values,
                query=query_values,
                headers=header_values,
                body=json_body,
                files=files,
                form=form,
            )
        ).content

    async def _generated_text(
        self,
        operation_id: OperationId,
        *,
        path: object,
        query: object,
        headers: object,
        body: object,
        body_media_type: str | None,
    ) -> str:
        path_values, query_values, header_values, json_body, files, form = (
            _generated_values(
                path=path,
                query=query,
                headers=headers,
                body=body,
                body_media_type=body_media_type,
            )
        )
        return (
            await self.request_raw(
                operation_id,
                path=path_values,
                query=query_values,
                headers=header_values,
                body=json_body,
                files=files,
                form=form,
            )
        ).text

    async def _generated_stream(
        self,
        operation_id: OperationId,
        *,
        path: object,
        query: object,
        headers: object,
        body: object,
        body_media_type: str | None,
    ) -> AsyncIterator[bytes]:
        path_values, query_values, header_values, _, _, _ = _generated_values(
            path=path,
            query=query,
            headers=headers,
            body=body,
            body_media_type=body_media_type,
        )
        async with self.stream(
            operation_id,
            path=path_values,
            query=query_values,
            headers=header_values,
        ) as response:
            async for chunk in response.aiter_bytes():
                yield chunk

    async def _generated_none(
        self,
        operation_id: OperationId,
        *,
        path: object,
        query: object,
        headers: object,
        body: object,
        body_media_type: str | None,
    ) -> None:
        await self._generated_bytes(
            operation_id,
            path=path,
            query=query,
            headers=headers,
            body=body,
            body_media_type=body_media_type,
        )

    async def request_raw(
        self,
        operation_id: OperationId,
        *,
        path: Mapping[str, Scalar] | None = None,
        query: Mapping[str, QueryValue] | StrictSchema | None = None,
        headers: Mapping[str, str] | None = None,
        body: StrictSchema | object | None = None,
        files: Mapping[str, UploadFile] | None = None,
        form: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        method, url, params, request_headers = _request_parts(
            operation_id,
            api_key=self._api_key,
            path=path,
            query=query,
            headers=headers,
        )
        response = await self._client.request(
            method,
            url,
            params=params,
            headers=request_headers,
            json=_json_body(body) if files is None else None,
            data=form,
            files=tuple(files.items()) if files is not None else None,
        )
        if not response.is_success:
            raise _api_error(response)
        return response

    async def request(
        self,
        operation_id: OperationId,
        response_type: TypeAdapter[ResponseT] | type[ResponseT],
        *,
        path: Mapping[str, Scalar] | None = None,
        query: Mapping[str, QueryValue] | StrictSchema | None = None,
        headers: Mapping[str, str] | None = None,
        body: StrictSchema | object | None = None,
        files: Mapping[str, UploadFile] | None = None,
        form: Mapping[str, str] | None = None,
    ) -> ResponseT:
        response = await self.request_raw(
            operation_id,
            path=path,
            query=query,
            headers=headers,
            body=body,
            files=files,
            form=form,
        )
        adapter = (
            response_type
            if isinstance(response_type, TypeAdapter)
            else TypeAdapter(response_type)
        )
        return adapter.validate_json(response.content)

    @asynccontextmanager
    async def stream(
        self,
        operation_id: OperationId,
        *,
        path: Mapping[str, Scalar] | None = None,
        query: Mapping[str, QueryValue] | StrictSchema | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[httpx.Response]:
        method, url, params, request_headers = _request_parts(
            operation_id,
            api_key=self._api_key,
            path=path,
            query=query,
            headers=headers,
        )
        async with self._client.stream(
            method, url, params=params, headers=request_headers
        ) as response:
            if not response.is_success:
                await response.aread()
                raise _api_error(response)
            yield response

    async def health(self) -> HealthData:
        return (await self.request("get_health", _HEALTH_ADAPTER)).data

    async def create_task(
        self, request: CreateTaskRequest, *, idempotency_key: str | None = None
    ) -> CreateTaskData:
        headers = (
            {"Idempotency-Key": idempotency_key}
            if idempotency_key is not None
            else None
        )
        return (
            await self.request(
                "create_task", _CREATE_TASK_ADAPTER, headers=headers, body=request
            )
        ).data

    async def get_task(self, task_id: str) -> TaskDetail:
        return (
            await self.request(
                "get_task", _TASK_DETAIL_ADAPTER, path={"task_id": task_id}
            )
        ).data

    async def list_tasks(self, query: TaskListQuery | None = None) -> TaskListResponse:
        return await self.request("list_tasks", _TASK_LIST_ADAPTER, query=query)

    async def get_result(self, task_id: str) -> ParseResult:
        return (
            await self.request(
                "get_task_result", _RESULT_ADAPTER, path={"task_id": task_id}
            )
        ).data

    async def upload_file(
        self, filename: str, content: UploadContent, mime_type: str
    ) -> UploadedFileDetail:
        return (
            await self.request(
                "upload_file",
                _UPLOAD_ADAPTER,
                files={"file": (filename, content, mime_type)},
            )
        ).data

    async def download_artifact(self, task_id: str, artifact_id: str) -> bytes:
        response = await self.request_raw(
            "download_task_artifact",
            path={"task_id": task_id, "artifact_id": artifact_id},
        )
        return response.content


__all__ = [
    "AsyncParserServeClient",
    "ParserServeApiError",
    "ParserServeClient",
    "QueryValue",
    "Scalar",
    "SdkErrorDetail",
    "SdkErrorResponse",
    "UploadContent",
    "UploadFile",
]
