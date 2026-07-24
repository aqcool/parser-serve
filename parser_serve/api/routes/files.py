"""Uploaded file metadata and content endpoints."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Path,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.responses import StreamingResponse

from ...control import (
    InvalidLeaseError,
    LeaseExpiredError,
    StageExecutionConflictError,
    StageScheduler,
)
from ...persistence import Database
from ...persistence.files import (
    ArtifactRepository,
    FileRepository,
    artifact_detail,
    uploaded_file_detail,
)
from ...security import ContentValidationError, inspect_content
from ...persistence.models import StageRecord, TaskRecord, UploadedFileRecord
from ...schema.artifact import ArtifactResponse, ArtifactType
from ...schema.common import FileId, MimeType, StageId, WorkerId
from ...schema.error import ErrorCode, ErrorResponse
from ...schema.file import UploadedFileResponse
from ...schema.management import SettingKey
from ...schema.stage import StageStatus
from ...storage import (
    Storage,
    StorageObjectTooLargeError,
)
from ..authentication import require_api_key, require_worker_api_key
from ..errors import ApiError
from ..dynamic_settings import effective_int_setting
from ..responses import api_response


router = APIRouter(
    prefix="/api/v1/files",
    tags=["files"],
    dependencies=[Depends(require_api_key)],
)
internal_router = APIRouter(
    prefix="/internal/v1/workers",
    tags=["worker-files"],
    dependencies=[Depends(require_worker_api_key)],
)

_mime_adapter = TypeAdapter(MimeType)
_file_responses: dict[int | str, dict[str, object]] = {404: {"model": ErrorResponse}}
_binary_response: dict[int | str, dict[str, object]] = {
    200: {
        "description": "Raw uploaded file bytes",
        "content": {
            "application/octet-stream": {
                "schema": {"type": "string", "format": "binary"}
            }
        },
    },
    404: {"model": ErrorResponse},
}


def _database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The file database is not configured",
            retryable=True,
        )
    return database


def _storage(request: Request) -> Storage:
    return request.app.state.storage


def _repository(request: Request) -> FileRepository:
    return request.app.state.file_repository


def _artifact_repository(request: Request) -> ArtifactRepository:
    return request.app.state.artifact_repository


def _scheduler(request: Request) -> StageScheduler:
    return request.app.state.stage_scheduler


def _filename(upload: UploadFile) -> str:
    candidate = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if (
        not candidate
        or candidate in {".", ".."}
        or len(candidate) > 512
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
    ):
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="The uploaded filename is invalid",
        )
    return candidate


def _mime_type(upload: UploadFile) -> str:
    try:
        return _mime_adapter.validate_python(
            (upload.content_type or "application/octet-stream").split(";", 1)[0]
        )
    except ValidationError as exc:
        raise ApiError(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            message="The uploaded MIME type is invalid",
        ) from exc


async def _upload_chunks(
    upload: UploadFile,
    prefix: bytes = b"",
) -> AsyncIterator[bytes]:
    if prefix:
        yield prefix
    while chunk := await upload.read(1024 * 1024):
        yield chunk


def _content_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"


async def _record(
    request: Request,
    file_id: str,
) -> UploadedFileRecord:
    try:
        async with _database(request).session_factory() as session:
            record = await _repository(request).get(
                session,
                file_id,
                now=request.app.state.clock(),
            )
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The file database is unavailable",
            retryable=True,
        ) from exc
    if record is None or not await _storage(request).exists(record.storage_key):
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="The uploaded file does not exist or has expired",
        )
    return record


def _stream_response(request: Request, record: UploadedFileRecord) -> StreamingResponse:
    return StreamingResponse(
        _storage(request).read(record.storage_key),
        media_type=record.mime_type,
        headers={
            "Content-Disposition": _content_disposition(record.filename),
            "Content-Length": str(record.size_bytes),
            "X-Content-SHA256": record.sha256,
        },
    )


@router.post(
    "",
    operation_id="upload_file",
    status_code=status.HTTP_201_CREATED,
    response_model=UploadedFileResponse,
    responses={
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
    },
)
async def upload_file(
    request: Request,
    file: Annotated[UploadFile, File(description="File content to parse")],
) -> UploadedFileResponse:
    filename = _filename(file)
    declared_mime_type = _mime_type(file)
    maximum_bytes = await effective_int_setting(
        request,
        SettingKey.MAXIMUM_UPLOAD_BYTES,
    )
    sample = await file.read(min(64 * 1024, maximum_bytes + 1))
    if len(sample) > maximum_bytes:
        await file.close()
        raise ApiError(
            status_code=413,
            code=ErrorCode.FILE_TOO_LARGE,
            message="The uploaded file exceeds maximum_upload_bytes",
        )
    try:
        inspection = inspect_content(
            filename=filename,
            declared_mime_type=declared_mime_type,
            sample=sample,
        )
    except ContentValidationError as exc:
        await file.close()
        raise ApiError(
            status_code=415,
            code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            message=str(exc),
        ) from exc
    mime_type = inspection.detected_mime_type
    media_category = inspection.media_category
    file_id = f"file_{uuid4().hex}"
    storage_key = f"uploads/{file_id[5:7]}/{file_id}"
    storage = _storage(request)
    try:
        stored = await storage.write(
            storage_key,
            _upload_chunks(file, sample),
            maximum_bytes=maximum_bytes,
        )
    except StorageObjectTooLargeError as exc:
        raise ApiError(
            status_code=413,
            code=ErrorCode.FILE_TOO_LARGE,
            message="The uploaded file exceeds maximum_upload_bytes",
        ) from exc
    finally:
        await file.close()

    try:
        async with _database(request).session_factory() as session:
            now = request.app.state.clock()
            retention_seconds = (
                request.app.state.settings.uploaded_file_retention_seconds
            )
            record = await _repository(request).create(
                session,
                file_id=file_id,
                filename=filename,
                mime_type=mime_type,
                media_category=media_category,
                stored=stored,
                now=now,
                expires_at=(
                    now + timedelta(seconds=retention_seconds)
                    if retention_seconds is not None
                    else None
                ),
            )
            await session.commit()
    except SQLAlchemyError as exc:
        await storage.delete(storage_key)
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The uploaded file metadata could not be stored",
            retryable=True,
        ) from exc
    return api_response(request, uploaded_file_detail(record))


@router.get(
    "/{file_id}",
    operation_id="get_uploaded_file",
    response_model=UploadedFileResponse,
    responses=_file_responses,
)
async def get_uploaded_file(
    request: Request,
    file_id: Annotated[FileId, Path()],
) -> UploadedFileResponse:
    return api_response(request, uploaded_file_detail(await _record(request, file_id)))


@router.get(
    "/{file_id}/content",
    operation_id="download_uploaded_file",
    response_class=StreamingResponse,
    responses=_binary_response,
)
async def download_uploaded_file(
    request: Request,
    file_id: Annotated[FileId, Path()],
) -> StreamingResponse:
    return _stream_response(request, await _record(request, file_id))


async def _worker_can_read(
    request: Request,
    *,
    worker_id: str,
    file_id: str,
) -> bool:
    async with _database(request).session_factory() as session:
        sources = await session.scalars(
            select(TaskRecord.source_payload)
            .join(StageRecord, StageRecord.task_id == TaskRecord.task_id)
            .where(
                StageRecord.worker_id == worker_id,
                StageRecord.status.in_(
                    [StageStatus.LEASED.value, StageStatus.RUNNING.value]
                ),
            )
        )
        return any(
            source.get("type") == "uploaded_file" and source.get("file_id") == file_id
            for source in sources
        )


@internal_router.get(
    "/{worker_id}/files/{file_id}/content",
    operation_id="download_worker_source_file",
    response_class=StreamingResponse,
    responses={**_binary_response, 403: {"model": ErrorResponse}},
)
async def download_worker_source_file(
    request: Request,
    worker_id: Annotated[str, Path(pattern=r"^worker_[a-zA-Z0-9_-]{8,64}$")],
    file_id: Annotated[FileId, Path()],
) -> StreamingResponse:
    bound_worker_id: str | None = getattr(
        request.state,
        "authenticated_worker_id",
        None,
    )
    if bound_worker_id is not None and bound_worker_id != worker_id:
        raise ApiError(
            status_code=403,
            code=ErrorCode.AUTHENTICATION_FAILED,
            message="The Worker API Key is bound to a different worker",
        )
    try:
        allowed = await _worker_can_read(
            request,
            worker_id=worker_id,
            file_id=file_id,
        )
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The file authorization database is unavailable",
            retryable=True,
        ) from exc
    if not allowed:
        raise ApiError(
            status_code=403,
            code=ErrorCode.AUTHENTICATION_FAILED,
            message="The Worker has no active lease for this file",
        )
    return _stream_response(request, await _record(request, file_id))


def _require_worker_identity(request: Request, worker_id: str) -> None:
    bound_worker_id: str | None = getattr(
        request.state,
        "authenticated_worker_id",
        None,
    )
    if bound_worker_id is not None and bound_worker_id != worker_id:
        raise ApiError(
            status_code=401,
            code=ErrorCode.AUTHENTICATION_FAILED,
            message="The Worker API Key is bound to a different worker",
        )


def _lease_error(exc: Exception) -> ApiError:
    if isinstance(exc, LeaseExpiredError):
        message = "The Stage lease has expired"
    elif isinstance(exc, InvalidLeaseError):
        message = "The Stage lease token or owner is invalid"
    else:
        message = "The Stage is not in the required execution state"
    return ApiError(
        status_code=409,
        code=ErrorCode.CONFLICT,
        message=message,
    )


async def _authorize_artifact_upload(
    request: Request,
    *,
    worker_id: str,
    stage_id: str,
    lease_token: str,
) -> str:
    try:
        async with _database(request).session_factory() as session:
            stage = await _scheduler(request).authorize_artifact_upload(
                session,
                stage_id=stage_id,
                worker_id=worker_id,
                lease_token=lease_token,
                now=request.app.state.clock(),
            )
    except (
        InvalidLeaseError,
        LeaseExpiredError,
        StageExecutionConflictError,
    ) as exc:
        raise _lease_error(exc) from exc
    except SQLAlchemyError as exc:
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The Stage lease database is unavailable",
            retryable=True,
        ) from exc
    if stage is None:
        raise ApiError(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            message="The Stage does not exist",
        )
    return stage.task_id


@internal_router.post(
    "/{worker_id}/stages/{stage_id}/artifacts",
    operation_id="upload_stage_artifact",
    status_code=status.HTTP_201_CREATED,
    response_model=ArtifactResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
    },
)
async def upload_stage_artifact(
    request: Request,
    response: Response,
    worker_id: Annotated[WorkerId, Path()],
    stage_id: Annotated[StageId, Path()],
    lease_token: Annotated[
        str,
        Form(
            pattern=r"^lease_[a-zA-Z0-9_-]{32,128}$",
            description="Opaque active Stage lease token issued to this Worker.",
            examples=["lease_01J000000000000000000000000000000"],
        ),
    ],
    artifact_type: Annotated[
        ArtifactType,
        Form(
            description="Typed role of the uploaded Stage Artifact.",
            examples=[ArtifactType.RESULT_JSON],
        ),
    ],
    idempotency_key: Annotated[
        str,
        Form(
            min_length=1,
            max_length=256,
            description="Stable key reused when retrying the same Artifact upload.",
            examples=["stage_01J00000000000000000000000:1:0"],
        ),
    ],
    file: Annotated[UploadFile, File(description="Stage Artifact content")],
) -> ArtifactResponse:
    _require_worker_identity(request, worker_id)
    await _authorize_artifact_upload(
        request,
        worker_id=worker_id,
        stage_id=stage_id,
        lease_token=lease_token,
    )
    filename = _filename(file)
    mime_type = _mime_type(file)
    artifact_id = f"artifact_{uuid4().hex}"
    storage_key = f"artifacts/{artifact_id[9:11]}/{artifact_id}"
    storage = _storage(request)
    try:
        stored = await storage.write(
            storage_key,
            _upload_chunks(file),
            maximum_bytes=await effective_int_setting(
                request,
                SettingKey.MAXIMUM_UPLOAD_BYTES,
            ),
        )
    except StorageObjectTooLargeError as exc:
        raise ApiError(
            status_code=413,
            code=ErrorCode.FILE_TOO_LARGE,
            message="The Artifact exceeds maximum_upload_bytes",
        ) from exc
    finally:
        await file.close()

    idempotency_digest = hashlib.sha256(idempotency_key.encode("utf-8")).digest()
    request_digest = hashlib.sha256(
        json.dumps(
            {
                "artifact_type": artifact_type.value,
                "filename": filename,
                "mime_type": mime_type,
                "size_bytes": stored.size_bytes,
                "sha256": stored.sha256,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).digest()
    try:
        async with _database(request).session_factory() as session:
            stage = await _scheduler(request).authorize_artifact_upload(
                session,
                stage_id=stage_id,
                worker_id=worker_id,
                lease_token=lease_token,
                now=request.app.state.clock(),
            )
            if stage is None:
                raise ApiError(
                    status_code=404,
                    code=ErrorCode.NOT_FOUND,
                    message="The Stage does not exist",
                )
            existing = await _artifact_repository(request).get_by_idempotency(
                session,
                stage_id=stage_id,
                idempotency_digest=idempotency_digest,
            )
            if existing is not None:
                await storage.delete(storage_key)
                if existing.request_digest != request_digest:
                    raise ApiError(
                        status_code=409,
                        code=ErrorCode.CONFLICT,
                        message=(
                            "The Artifact idempotency key was already used "
                            "with different content"
                        ),
                    )
                response.status_code = status.HTTP_200_OK
                return api_response(request, artifact_detail(existing))
            artifact_now = request.app.state.clock()
            artifact_retention_seconds = (
                request.app.state.settings.artifact_retention_seconds
            )
            record = await _artifact_repository(request).create(
                session,
                task_id=stage.task_id,
                stage_id=stage_id,
                worker_id=worker_id,
                artifact_type=artifact_type,
                filename=filename,
                mime_type=mime_type,
                stored=stored,
                now=artifact_now,
                expires_at=(
                    artifact_now + timedelta(seconds=artifact_retention_seconds)
                    if artifact_retention_seconds is not None
                    else None
                ),
                artifact_id=artifact_id,
                idempotency_digest=idempotency_digest,
                request_digest=request_digest,
                metadata={
                    "stage_id": stage_id,
                    "worker_id": worker_id,
                },
            )
            await session.commit()
    except (
        InvalidLeaseError,
        LeaseExpiredError,
        StageExecutionConflictError,
    ) as exc:
        await storage.delete(storage_key)
        raise _lease_error(exc) from exc
    except IntegrityError as exc:
        await storage.delete(storage_key)
        try:
            async with _database(request).session_factory() as session:
                existing = await _artifact_repository(request).get_by_idempotency(
                    session,
                    stage_id=stage_id,
                    idempotency_digest=idempotency_digest,
                )
        except SQLAlchemyError as lookup_exc:
            raise ApiError(
                status_code=503,
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="The Artifact idempotency state is unavailable",
                retryable=True,
            ) from lookup_exc
        if existing is None:
            raise ApiError(
                status_code=503,
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="The Artifact metadata could not be stored",
                retryable=True,
            ) from exc
        if existing.request_digest != request_digest:
            raise ApiError(
                status_code=409,
                code=ErrorCode.CONFLICT,
                message=(
                    "The Artifact idempotency key was already used "
                    "with different content"
                ),
            ) from exc
        response.status_code = status.HTTP_200_OK
        return api_response(request, artifact_detail(existing))
    except SQLAlchemyError as exc:
        await storage.delete(storage_key)
        raise ApiError(
            status_code=503,
            code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="The Artifact metadata could not be stored",
            retryable=True,
        ) from exc
    except ApiError:
        await storage.delete(storage_key)
        raise
    return api_response(request, artifact_detail(record))


__all__ = ["internal_router", "router"]
