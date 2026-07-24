"""Typed HTTP client for the internal Worker protocol."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Protocol

import httpx

from ..backends.base import ProducedArtifact
from ..schema.artifact import Artifact, ArtifactResponse
from ..schema.error import ErrorCode, ErrorDetail, ErrorResponse
from ..schema.worker import (
    CompleteStageRequest,
    LeasedStage,
    RenewStageLeaseRequest,
    RenewStageLeaseResponse,
    StageProgressRequest,
    StartStageRequest,
    WorkerDetailResponse,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerLeaseRequest,
    WorkerLeaseResponse,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
)


class ControlPlaneError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        detail: ErrorDetail,
    ) -> None:
        super().__init__(detail.message)
        self.status_code = status_code
        self.detail = detail


class WorkerControlClient(Protocol):
    async def register(
        self,
        request: WorkerRegistrationRequest,
    ) -> WorkerRegistrationResponse: ...

    async def heartbeat(
        self,
        request: WorkerHeartbeatRequest,
    ) -> WorkerHeartbeatResponse: ...

    async def drain(self, worker_id: str) -> WorkerDetailResponse: ...

    async def lease(self, request: WorkerLeaseRequest) -> tuple[LeasedStage, ...]: ...

    async def start(self, lease: LeasedStage, worker_id: str) -> None: ...

    async def renew(self, lease: LeasedStage, worker_id: str) -> None: ...

    async def progress(
        self,
        lease: LeasedStage,
        worker_id: str,
        progress_percent: float,
    ) -> None: ...

    async def download_source(
        self,
        *,
        worker_id: str,
        file_id: str,
        destination: Path,
        expected_size_bytes: int,
        expected_sha256: str,
    ) -> Path: ...

    async def upload_artifact(
        self,
        *,
        worker_id: str,
        lease: LeasedStage,
        artifact: ProducedArtifact,
        idempotency_key: str,
    ) -> Artifact: ...

    async def complete(
        self,
        lease: LeasedStage,
        request: CompleteStageRequest,
    ) -> None: ...


class HttpWorkerControlClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def __aenter__(self) -> HttpWorkerControlClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _json_post(
        self,
        path: str,
        payload: dict[str, object],
    ) -> httpx.Response:
        response = await self._client.post(path, json=payload)
        self._raise_for_error(response)
        return response

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            detail = ErrorResponse.model_validate_json(response.content).error
        except Exception:
            response.raise_for_status()
            raise AssertionError("unreachable")
        raise ControlPlaneError(response.status_code, detail)

    async def register(
        self,
        request: WorkerRegistrationRequest,
    ) -> WorkerRegistrationResponse:
        response = await self._json_post(
            "/internal/v1/workers/register",
            request.model_dump(mode="json"),
        )
        return WorkerRegistrationResponse.model_validate_json(response.content)

    async def heartbeat(
        self,
        request: WorkerHeartbeatRequest,
    ) -> WorkerHeartbeatResponse:
        response = await self._json_post(
            "/internal/v1/workers/heartbeat",
            request.model_dump(mode="json"),
        )
        return WorkerHeartbeatResponse.model_validate_json(response.content)

    async def drain(self, worker_id: str) -> WorkerDetailResponse:
        response = await self._json_post(
            f"/internal/v1/workers/{worker_id}/drain",
            {},
        )
        return WorkerDetailResponse.model_validate_json(response.content)

    async def lease(self, request: WorkerLeaseRequest) -> tuple[LeasedStage, ...]:
        response = await self._json_post(
            "/internal/v1/workers/lease",
            request.model_dump(mode="json"),
        )
        parsed = WorkerLeaseResponse.model_validate_json(response.content)
        return tuple(parsed.data.leases)

    async def start(self, lease: LeasedStage, worker_id: str) -> None:
        request = StartStageRequest(
            worker_id=worker_id,
            lease_token=lease.lease_token,
        )
        await self._json_post(
            f"/internal/v1/workers/stages/{lease.stage_id}/start",
            request.model_dump(mode="json"),
        )

    async def renew(self, lease: LeasedStage, worker_id: str) -> None:
        request = RenewStageLeaseRequest(
            worker_id=worker_id,
            lease_token=lease.lease_token,
        )
        response = await self._json_post(
            f"/internal/v1/workers/stages/{lease.stage_id}/renew",
            request.model_dump(mode="json"),
        )
        RenewStageLeaseResponse.model_validate_json(response.content)

    async def progress(
        self,
        lease: LeasedStage,
        worker_id: str,
        progress_percent: float,
    ) -> None:
        request = StageProgressRequest(
            worker_id=worker_id,
            lease_token=lease.lease_token,
            progress_percent=progress_percent,
        )
        await self._json_post(
            f"/internal/v1/workers/stages/{lease.stage_id}/progress",
            request.model_dump(mode="json"),
        )

    async def download_source(
        self,
        *,
        worker_id: str,
        file_id: str,
        destination: Path,
        expected_size_bytes: int,
        expected_sha256: str,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self._client.stream(
            "GET",
            f"/internal/v1/workers/{worker_id}/files/{file_id}/content",
        ) as response:
            if not response.is_success:
                await response.aread()
                self._raise_for_error(response)
            declared_size = response.headers.get("Content-Length")
            declared_sha256 = response.headers.get("X-Content-SHA256")
            if (
                declared_size != str(expected_size_bytes)
                or declared_sha256 != expected_sha256
            ):
                raise ControlPlaneError(
                    response.status_code,
                    ErrorDetail(
                        code=ErrorCode.VALIDATION_ERROR,
                        message="source file metadata does not match the lease",
                    ),
                )
            handle = await asyncio.to_thread(destination.open, "wb")
            digest = hashlib.sha256()
            size = 0
            try:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > expected_size_bytes:
                        raise ControlPlaneError(
                            response.status_code,
                            ErrorDetail(
                                code=ErrorCode.FILE_TOO_LARGE,
                                message="source file exceeds its declared size",
                            ),
                        )
                    digest.update(chunk)
                    await asyncio.to_thread(handle.write, chunk)
            except BaseException:
                await asyncio.to_thread(handle.close)
                await asyncio.to_thread(destination.unlink, missing_ok=True)
                raise
            await asyncio.to_thread(handle.close)
            if size != expected_size_bytes or digest.hexdigest() != expected_sha256:
                await asyncio.to_thread(destination.unlink, missing_ok=True)
                raise ControlPlaneError(
                    response.status_code,
                    ErrorDetail(
                        code=ErrorCode.VALIDATION_ERROR,
                        message="source file content failed integrity validation",
                    ),
                )
        return destination

    async def upload_artifact(
        self,
        *,
        worker_id: str,
        lease: LeasedStage,
        artifact: ProducedArtifact,
        idempotency_key: str,
    ) -> Artifact:
        content: bytes
        if artifact.data is not None:
            content = artifact.data
        elif artifact.path is not None:
            content = await asyncio.to_thread(artifact.path.read_bytes)
        else:
            raise AssertionError("ProducedArtifact invariant was violated")
        response = await self._client.post(
            (f"/internal/v1/workers/{worker_id}/stages/{lease.stage_id}/artifacts"),
            data={
                "lease_token": lease.lease_token,
                "artifact_type": artifact.type.value,
                "idempotency_key": idempotency_key,
            },
            files={
                "file": (
                    artifact.filename,
                    content,
                    artifact.mime_type,
                )
            },
        )
        self._raise_for_error(response)
        return ArtifactResponse.model_validate_json(response.content).data

    async def complete(
        self,
        lease: LeasedStage,
        request: CompleteStageRequest,
    ) -> None:
        await self._json_post(
            f"/internal/v1/workers/stages/{lease.stage_id}/complete",
            request.model_dump(mode="json"),
        )


__all__ = [
    "ControlPlaneError",
    "HttpWorkerControlClient",
    "WorkerControlClient",
]
