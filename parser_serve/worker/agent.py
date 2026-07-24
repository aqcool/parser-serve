"""Backend-neutral pull/lease Worker execution loop."""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
from pathlib import Path, PurePath

from ..backends import (
    BackendContext,
    BackendExecutionError,
    BackendRegistry,
)
from ..schema.error import ErrorCode, ErrorDetail
from ..schema.source import (
    ObjectStorageSource,
    TextSource,
    UploadedFileSource,
    UrlSource,
)
from ..security import ContentValidationError, inspect_content
from ..observability import log_context
from ..observability import trace_span
from ..schema.worker import (
    CompleteStageRequest,
    LeasedStage,
    WorkerLeaseRequest,
)
from .client import WorkerControlClient
from .preprocessors import SourcePreprocessor, builtin_preprocessors
from .object_storage import download_object_storage_source
from .url_fetcher import fetch_url_source
from ..utils.process_limits import ProcessResourceLimits


def _read_sample(path: Path) -> bytes:
    with path.open("rb") as source:
        return source.read(64 * 1024)


class WorkerAgent:
    def __init__(
        self,
        *,
        worker_id: str,
        client: WorkerControlClient,
        backends: BackendRegistry,
        maximum_concurrency: int,
        lease_wait_seconds: float = 0.0,
        lease_renew_interval_seconds: float = 20.0,
        preprocessors: tuple[SourcePreprocessor, ...] | None = None,
        maximum_url_download_bytes: int = 25 * 1024 * 1024,
        url_download_timeout_seconds: float = 30.0,
        maximum_url_redirects: int = 5,
        allowed_s3_buckets: set[str] | None = None,
        s3_endpoint_url: str | None = None,
        s3_region_name: str | None = None,
        maximum_object_download_bytes: int = 100 * 1024 * 1024,
        process_resource_limits: ProcessResourceLimits | None = None,
    ) -> None:
        if maximum_concurrency < 1:
            raise ValueError("maximum_concurrency must be greater than zero")
        if lease_renew_interval_seconds <= 0:
            raise ValueError("lease renewal interval must be greater than zero")
        if not 0 <= lease_wait_seconds <= 30:
            raise ValueError("lease wait must be between zero and 30 seconds")
        if (
            maximum_url_download_bytes < 1
            or url_download_timeout_seconds <= 0
            or maximum_url_redirects < 0
            or maximum_object_download_bytes < 1
        ):
            raise ValueError("URL download limits are invalid")
        self.worker_id = worker_id
        self.client = client
        self.backends = backends
        self.maximum_concurrency = maximum_concurrency
        self.lease_wait_seconds = lease_wait_seconds
        self.lease_renew_interval_seconds = lease_renew_interval_seconds
        self.preprocessors = preprocessors or builtin_preprocessors(
            resource_limits=process_resource_limits
        )
        self.maximum_url_download_bytes = maximum_url_download_bytes
        self.url_download_timeout_seconds = url_download_timeout_seconds
        self.maximum_url_redirects = maximum_url_redirects
        self.allowed_s3_buckets = allowed_s3_buckets or set()
        self.s3_endpoint_url = s3_endpoint_url
        self.s3_region_name = s3_region_name
        self.maximum_object_download_bytes = maximum_object_download_bytes
        self._active_count = 0
        self._backend_semaphores = {
            (capability.name, capability.version): asyncio.Semaphore(
                capability.maximum_concurrency
            )
            for capability in backends.capabilities
        }

    @property
    def active_count(self) -> int:
        return self._active_count

    async def run_once(self) -> int:
        leases = await self.client.lease(
            WorkerLeaseRequest(
                worker_id=self.worker_id,
                available_slots=self.maximum_concurrency,
                wait_seconds=self.lease_wait_seconds,
            )
        )
        if leases:
            await asyncio.gather(*(self.execute(lease) for lease in leases))
        return len(leases)

    async def execute(self, lease: LeasedStage) -> bool:
        self._active_count += 1
        try:
            with log_context(
                task_id=lease.task_id,
                stage_id=lease.stage_id,
                worker_id=self.worker_id,
            ):
                with trace_span(
                    "parser.stage.execute",
                    parent=lease.trace_context,
                    attributes={
                        "parser.task.id": lease.task_id,
                        "parser.stage.id": lease.stage_id,
                        "parser.worker.id": self.worker_id,
                        "parser.backend.name": lease.backend_name,
                        "parser.runtime": lease.runtime.value,
                        **(
                            {"parser.device.id": lease.device_id}
                            if lease.device_id is not None
                            else {}
                        ),
                    },
                ):
                    return await self._execute(lease)
        finally:
            self._active_count -= 1

    async def _execute(self, lease: LeasedStage) -> bool:
        await self.client.start(lease, self.worker_id)
        stop_renewal = asyncio.Event()
        renewal = asyncio.create_task(self._renew_loop(lease, stop_renewal))
        work = asyncio.create_task(self._produce_result_uri(lease))
        try:
            done, _ = await asyncio.wait(
                {work, renewal},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if renewal in done:
                renewal_error = renewal.exception()
                if renewal_error is not None:
                    raise BackendExecutionError(
                        f"Stage lease renewal failed: {type(renewal_error).__name__}",
                        retryable=True,
                    ) from renewal_error
            result_uri = await work
            await self.client.complete(
                lease,
                CompleteStageRequest(
                    worker_id=self.worker_id,
                    lease_token=lease.lease_token,
                    status="succeeded",
                    result_uri=result_uri,
                ),
            )
            return True
        except asyncio.TimeoutError:
            error = ErrorDetail(
                code=ErrorCode.TIMEOUT,
                message=f"Backend execution exceeded {lease.timeout_seconds} seconds",
                retryable=True,
            )
        except BackendExecutionError as exc:
            error = ErrorDetail(
                code=ErrorCode.BACKEND_NOT_AVAILABLE,
                message=str(exc),
                retryable=exc.retryable,
            )
        except Exception as exc:
            error = ErrorDetail(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Worker execution failed: {type(exc).__name__}",
                retryable=False,
            )
        finally:
            stop_renewal.set()
            for task in (work, renewal):
                if not task.done():
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

        await self.client.complete(
            lease,
            CompleteStageRequest(
                worker_id=self.worker_id,
                lease_token=lease.lease_token,
                status="failed",
                error=error,
            ),
        )
        return False

    async def _produce_result_uri(self, lease: LeasedStage) -> str:
        with tempfile.TemporaryDirectory(
            prefix=f"parser-serve-{lease.stage_id}-"
        ) as temporary:
            work_dir = Path(temporary)
            source_path, source_text = await self._resolve_source(
                lease,
                work_dir=work_dir,
            )
            if source_path is not None:
                for preprocessor in self.preprocessors:
                    if preprocessor.applies_to(source_path):
                        source_path = await preprocessor.prepare(
                            source_path,
                            work_dir=work_dir,
                            timeout_seconds=lease.timeout_seconds,
                        )

            async def report_progress(progress_percent: float) -> None:
                await self.client.progress(
                    lease,
                    self.worker_id,
                    progress_percent,
                )

            backend = self.backends.get(
                lease.backend_name,
                lease.backend_version,
            )
            semaphore = self._backend_semaphores[
                (lease.backend_name, lease.backend_version)
            ]
            async with semaphore:
                output = await asyncio.wait_for(
                    backend.execute(
                        BackendContext(
                            lease=lease,
                            work_dir=work_dir,
                            source_path=source_path,
                            source_text=source_text,
                            report_progress=report_progress,
                        )
                    ),
                    timeout=float(lease.timeout_seconds),
                )
            uploaded = [
                await self.client.upload_artifact(
                    worker_id=self.worker_id,
                    lease=lease,
                    artifact=artifact,
                    idempotency_key=f"{lease.stage_id}:{lease.attempt}:{index}",
                )
                for index, artifact in enumerate(output.artifacts)
            ]
            return uploaded[output.primary_artifact_index].storage_uri

    async def _resolve_source(
        self,
        lease: LeasedStage,
        *,
        work_dir: Path,
    ) -> tuple[Path | None, str | None]:
        if isinstance(lease.source, TextSource):
            return None, lease.source.text
        if isinstance(lease.source, UploadedFileSource):
            filename = lease.source_metadata.filename or "source.bin"
            filename = PurePath(filename.replace("\\", "/")).name
            if not filename or filename in {".", ".."}:
                filename = "source.bin"
            if (
                lease.source_metadata.size_bytes is None
                or lease.source_metadata.sha256 is None
            ):
                raise BackendExecutionError(
                    "uploaded file metadata requires size_bytes and sha256"
                )
            path = work_dir / "source" / filename
            downloaded = await self.client.download_source(
                worker_id=self.worker_id,
                file_id=lease.source.file_id,
                destination=path,
                expected_size_bytes=lease.source_metadata.size_bytes,
                expected_sha256=lease.source_metadata.sha256,
            )
            await self._validate_source_content(downloaded, lease)
            return downloaded, None
        if isinstance(lease.source, UrlSource):
            filename = lease.source_metadata.filename or "index.html"
            filename = PurePath(filename.replace("\\", "/")).name
            if not filename or filename in {".", ".."}:
                filename = "index.html"
            return (
                await fetch_url_source(
                    lease.source.url,
                    work_dir / "source" / filename,
                    maximum_bytes=self.maximum_url_download_bytes,
                    timeout_seconds=self.url_download_timeout_seconds,
                    maximum_redirects=self.maximum_url_redirects,
                ),
                None,
            )
        if isinstance(lease.source, ObjectStorageSource):
            filename = lease.source_metadata.filename or "source.bin"
            filename = PurePath(filename.replace("\\", "/")).name
            if not filename or filename in {".", ".."}:
                filename = "source.bin"
            return (
                await download_object_storage_source(
                    lease.source.uri,
                    work_dir / "source" / filename,
                    allowed_buckets=self.allowed_s3_buckets,
                    maximum_bytes=self.maximum_object_download_bytes,
                    declared_mime_type=lease.source_metadata.mime_type,
                    version_id=lease.source.version_id,
                    endpoint_url=self.s3_endpoint_url,
                    region_name=self.s3_region_name,
                ),
                None,
            )
        raise BackendExecutionError(
            f"source type {lease.source.type!r} is not supported by this Worker"
        )

    @staticmethod
    async def _validate_source_content(path: Path, lease: LeasedStage) -> None:
        sample = await asyncio.to_thread(_read_sample, path)
        try:
            inspect_content(
                filename=path.name,
                declared_mime_type=lease.source_metadata.mime_type,
                sample=sample,
            )
        except ContentValidationError as exc:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise BackendExecutionError(str(exc)) from exc

    async def _renew_loop(
        self,
        lease: LeasedStage,
        stop: asyncio.Event,
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self.lease_renew_interval_seconds,
                )
                return
            except TimeoutError:
                await self.client.renew(lease, self.worker_id)


__all__ = ["WorkerAgent"]
