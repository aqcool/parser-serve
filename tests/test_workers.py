from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from parser_serve.control import (
    InvalidLeaseError,
    StageScheduler,
    TaskRouter,
)
from parser_serve.persistence import Database
from parser_serve.persistence.registry import BackendRepository, PipelineRepository
from parser_serve.persistence.tasks import TaskRepository, task_detail
from parser_serve.persistence.workers import (
    StaleHeartbeatError,
    WorkerRepository,
    worker_detail,
)
from parser_serve.schema.backend import (
    BackendCapability,
    BackendExecutionMode,
    CreateBackendRequest,
)
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.error import ErrorCode, ErrorDetail
from parser_serve.schema.hardware import (
    DeviceInfo,
    DeviceRequirement,
    DeviceRuntime,
    DeviceUsage,
    HardwareVendor,
)
from parser_serve.schema.management import UpdateWorkerRequest
from parser_serve.schema.pipeline import (
    BackendSelector,
    CreatePipelineRequest,
    PipelineStageDefinition,
    RetryPolicy,
)
from parser_serve.schema.task import (
    CreateTaskRequest,
    TaskListQuery,
    TaskOptions,
    TaskStatus,
)
from parser_serve.schema.trace import TraceContext
from parser_serve.schema.stage import StageStatus
from parser_serve.schema.worker import (
    CompleteStageRequest,
    StageProgressRequest,
    WorkerHeartbeatRequest,
    WorkerLeaseRequest,
    WorkerRegistrationRequest,
    WorkerResourceUsage,
    WorkerStatus,
)


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
WORKER_ID = "worker_cpuworker"


def capability(
    runtimes: list[DeviceRuntime] | None = None,
) -> BackendCapability:
    return BackendCapability(
        name="text_backend",
        version="1.0",
        media_categories=[MediaCategory.TEXT],
        runtimes=runtimes or [DeviceRuntime.CPU],
        maximum_concurrency=4,
    )


def registration(
    *,
    worker_id: str = WORKER_ID,
    runtime: DeviceRuntime = DeviceRuntime.CPU,
) -> WorkerRegistrationRequest:
    vendor = (
        HardwareVendor.NVIDIA
        if runtime is DeviceRuntime.CUDA
        else HardwareVendor.GENERIC
    )
    return WorkerRegistrationRequest(
        worker_id=worker_id,
        name=f"{runtime.value.upper()} Worker",
        version="0.1.0",
        hostname="worker-01",
        devices=[
            DeviceInfo(
                device_id=f"{runtime.value}-0",
                vendor=vendor,
                runtime=runtime,
                model=f"Test {runtime.value.upper()}",
                total_memory_bytes=1000,
            )
        ],
        backends=[capability([runtime])],
        labels={"zone": "local"},
        maximum_concurrency=2,
    )


class WorkerAndSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database("sqlite+aiosqlite:///:memory:")
        await self.database.create_schema_for_testing()
        self.workers = WorkerRepository()
        self.backends = BackendRepository()
        self.pipelines = PipelineRepository()
        self.tasks = TaskRepository()
        self.scheduler = StageScheduler(lease_duration_seconds=30)

    async def asyncTearDown(self) -> None:
        await self.database.dispose()

    async def prepare_routed_task(
        self,
        *,
        maximum_attempts: int = 1,
        minimum_memory_bytes: int | None = None,
        worker_labels: dict[str, str] | None = None,
        backend_runtimes: list[DeviceRuntime] | None = None,
        preferred_runtimes: list[DeviceRuntime] | None = None,
        trace_context: TraceContext | None = None,
    ) -> str:
        async with self.database.session_factory() as session:
            await self.backends.create(
                session,
                request=CreateBackendRequest(
                    capability=capability(backend_runtimes),
                    execution_mode=BackendExecutionMode.LOCAL,
                    default_timeout_seconds=60,
                ),
                now=NOW,
            )
            pipeline = await self.pipelines.create(
                session,
                request=CreatePipelineRequest(
                    pipeline_id="pipeline_textparse",
                    name="Text Pipeline",
                    media_categories=[MediaCategory.TEXT],
                    stages=[
                        PipelineStageDefinition(
                            name="extract",
                            backend=BackendSelector(preferred="text_backend"),
                            timeout_seconds=60,
                            retry=RetryPolicy(
                                maximum_attempts=maximum_attempts,
                                initial_delay_seconds=1.0,
                                maximum_delay_seconds=10.0,
                            ),
                        ),
                        PipelineStageDefinition(
                            name="normalize",
                            backend=BackendSelector(preferred="text_backend"),
                            depends_on=["extract"],
                            timeout_seconds=60,
                        ),
                    ],
                ),
                now=NOW,
            )
            await self.pipelines.publish(
                session,
                pipeline_id=pipeline.pipeline_id,
                version=pipeline.version,
                now=NOW,
            )
            task_payload: dict[str, object] = {
                "source": {"type": "text", "text": "hello"}
            }
            if minimum_memory_bytes is not None or worker_labels or preferred_runtimes:
                task_payload["options"] = {
                    "device": {
                        "strategy": ("prefer" if preferred_runtimes else "auto"),
                        "runtimes": preferred_runtimes or [],
                        "minimum_memory_bytes": minimum_memory_bytes,
                        "worker_labels": worker_labels or {},
                    }
                }
            task, _ = await self.tasks.create(
                session,
                request=CreateTaskRequest.model_validate(task_payload),
                idempotency_key=None,
                now=NOW,
                trace_context=trace_context,
            )
            await TaskRouter().route(
                session,
                task_id=task.task_id,
                now=NOW,
            )
            await self.workers.register(session, request=registration(), now=NOW)
            await session.commit()
            return task.task_id

    async def test_persisted_trace_context_is_carried_by_stage_lease(self) -> None:
        context = TraceContext(
            traceparent=("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
        )
        await self.prepare_routed_task(trace_context=context)

        async with self.database.session_factory() as session:
            lease = (
                await self.scheduler.lease(
                    session,
                    request=WorkerLeaseRequest(
                        worker_id=WORKER_ID,
                        available_slots=1,
                    ),
                    now=NOW,
                )
            )[0]

        self.assertEqual(lease.trace_context, context)

    async def test_worker_registration_and_monotonic_heartbeat(self) -> None:
        async with self.database.session_factory() as session:
            record = await self.workers.register(
                session,
                request=registration(),
                now=NOW,
            )
            await session.commit()
        self.assertEqual(worker_detail(record).status, WorkerStatus.ONLINE)

        heartbeat = WorkerHeartbeatRequest(
            worker_id=WORKER_ID,
            sequence=1,
            status=WorkerStatus.ONLINE,
            resources=WorkerResourceUsage(
                cpu_percent=10.0,
                memory_used_bytes=100,
                memory_total_bytes=1000,
                running_tasks=0,
                leased_tasks=0,
            ),
            timestamp=NOW + timedelta(seconds=1),
        )
        async with self.database.session_factory() as session:
            updated = await self.workers.heartbeat(
                session,
                request=heartbeat,
                now=NOW + timedelta(seconds=1),
            )
            await session.commit()
        self.assertIsNotNone(updated)
        if updated is not None:
            self.assertEqual(updated.heartbeat_sequence, 1)

        async with self.database.session_factory() as session:
            with self.assertRaises(StaleHeartbeatError):
                await self.workers.heartbeat(
                    session,
                    request=heartbeat,
                    now=NOW + timedelta(seconds=2),
                )

    async def test_pull_start_progress_and_complete_dag(self) -> None:
        task_id = await self.prepare_routed_task()

        async with self.database.session_factory() as session:
            leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=2,
                ),
                now=NOW,
            )
            await session.commit()
        self.assertEqual([lease.stage_name for lease in leases], ["extract"])
        first = leases[0]

        async with self.database.session_factory() as session:
            started = await self.scheduler.start(
                session,
                stage_id=first.stage_id,
                worker_id=WORKER_ID,
                lease_token=first.lease_token,
                now=NOW + timedelta(seconds=1),
            )
            progressed = await self.scheduler.progress(
                session,
                stage_id=first.stage_id,
                request=StageProgressRequest(
                    worker_id=WORKER_ID,
                    lease_token=first.lease_token,
                    progress_percent=50.0,
                ),
                now=NOW + timedelta(seconds=2),
            )
            completed = await self.scheduler.complete(
                session,
                stage_id=first.stage_id,
                request=CompleteStageRequest(
                    worker_id=WORKER_ID,
                    lease_token=first.lease_token,
                    status="succeeded",
                ),
                now=NOW + timedelta(seconds=3),
            )
            await session.commit()
        self.assertIsNotNone(started)
        self.assertIsNotNone(progressed)
        self.assertIsNotNone(completed)
        if progressed is not None:
            self.assertEqual(progressed.progress_percent, 25.0)

        async with self.database.session_factory() as session:
            leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW + timedelta(seconds=4),
            )
            await session.commit()
        self.assertEqual([lease.stage_name for lease in leases], ["normalize"])
        second = leases[0]

        async with self.database.session_factory() as session:
            await self.scheduler.start(
                session,
                stage_id=second.stage_id,
                worker_id=WORKER_ID,
                lease_token=second.lease_token,
                now=NOW + timedelta(seconds=5),
            )
            final = await self.scheduler.complete(
                session,
                stage_id=second.stage_id,
                request=CompleteStageRequest(
                    worker_id=WORKER_ID,
                    lease_token=second.lease_token,
                    status="succeeded",
                    result_uri="s3://results/result.json",
                ),
                now=NOW + timedelta(seconds=6),
            )
            await session.commit()
        self.assertIsNotNone(final)
        if final is not None:
            self.assertEqual(final.task_status, TaskStatus.SUCCEEDED)
            self.assertEqual(final.progress_percent, 100.0)

        async with self.database.session_factory() as session:
            task = await self.tasks.get(session, task_id)
        self.assertIsNotNone(task)
        if task is not None:
            self.assertEqual(
                task_detail(task).result_uri,
                "s3://results/result.json",
            )

    async def test_invalid_token_is_rejected(self) -> None:
        await self.prepare_routed_task()
        async with self.database.session_factory() as session:
            leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            with self.assertRaises(InvalidLeaseError):
                await self.scheduler.start(
                    session,
                    stage_id=leases[0].stage_id,
                    worker_id=WORKER_ID,
                    lease_token=f"lease_{'x' * 43}",
                    now=NOW + timedelta(seconds=1),
                )

    async def test_lease_respects_worker_labels_and_available_memory(self) -> None:
        await self.prepare_routed_task(
            minimum_memory_bytes=2000,
            worker_labels={"zone": "local"},
        )
        async with self.database.session_factory() as session:
            leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW,
            )
        self.assertEqual(leases, [])

        async with self.database.session_factory() as session:
            tasks = await self.tasks.list(
                session,
                query=TaskListQuery(),
            )
            tasks[0].options_payload = TaskOptions(
                device=DeviceRequirement(
                    minimum_memory_bytes=500,
                    worker_labels={"zone": "other"},
                )
            ).model_dump(mode="json")
            await session.commit()
        async with self.database.session_factory() as session:
            leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW,
            )
        self.assertEqual(leases, [])

    async def test_memory_pressure_blocks_new_leases_until_recovered(self) -> None:
        await self.prepare_routed_task()

        async def heartbeat(sequence: int, used_bytes: int) -> None:
            async with self.database.session_factory() as session:
                await self.workers.heartbeat(
                    session,
                    request=WorkerHeartbeatRequest(
                        worker_id=WORKER_ID,
                        sequence=sequence,
                        status=WorkerStatus.ONLINE,
                        resources=WorkerResourceUsage(
                            cpu_percent=10.0,
                            memory_used_bytes=used_bytes,
                            memory_total_bytes=1000,
                            running_tasks=0,
                            leased_tasks=0,
                        ),
                        devices=[
                            DeviceUsage(
                                device_id="cpu-0",
                                utilization_percent=10.0,
                                memory_used_bytes=used_bytes,
                                memory_total_bytes=1000,
                            )
                        ],
                        timestamp=NOW + timedelta(seconds=sequence),
                    ),
                    now=NOW + timedelta(seconds=sequence),
                )
                await session.commit()

        await heartbeat(1, 950)
        async with self.database.session_factory() as session:
            blocked = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW + timedelta(seconds=1),
            )
        self.assertEqual(blocked, [])

        await heartbeat(2, 500)
        async with self.database.session_factory() as session:
            recovered = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW + timedelta(seconds=2),
            )
            await session.commit()
        self.assertEqual(len(recovered), 1)

    async def test_multi_gpu_leases_are_assigned_to_distinct_devices(self) -> None:
        await self.prepare_routed_task(
            backend_runtimes=[DeviceRuntime.CUDA],
            preferred_runtimes=[DeviceRuntime.CUDA],
        )
        cuda_devices = [
            DeviceInfo(
                device_id=f"cuda-{index}",
                vendor=HardwareVendor.NVIDIA,
                runtime=DeviceRuntime.CUDA,
                model=f"Test GPU {index}",
                total_memory_bytes=10_000,
            )
            for index in range(2)
        ]
        async with self.database.session_factory() as session:
            await self.workers.register(
                session,
                request=registration(runtime=DeviceRuntime.CUDA).model_copy(
                    update={"devices": cuda_devices}
                ),
                now=NOW,
            )
            await self.workers.heartbeat(
                session,
                request=WorkerHeartbeatRequest(
                    worker_id=WORKER_ID,
                    sequence=1,
                    status=WorkerStatus.ONLINE,
                    resources=WorkerResourceUsage(
                        cpu_percent=5.0,
                        memory_used_bytes=100,
                        memory_total_bytes=1000,
                        running_tasks=0,
                        leased_tasks=0,
                    ),
                    devices=[
                        DeviceUsage(
                            device_id="cuda-0",
                            utilization_percent=80.0,
                            memory_used_bytes=8_000,
                            memory_total_bytes=10_000,
                        ),
                        DeviceUsage(
                            device_id="cuda-1",
                            utilization_percent=10.0,
                            memory_used_bytes=1_000,
                            memory_total_bytes=10_000,
                        ),
                    ],
                    timestamp=NOW,
                ),
                now=NOW,
            )
            second, _ = await self.tasks.create(
                session,
                request=CreateTaskRequest.model_validate(
                    {
                        "source": {"type": "text", "text": "second task"},
                        "options": {
                            "device": {
                                "strategy": "prefer",
                                "runtimes": ["cuda"],
                            }
                        },
                    }
                ),
                idempotency_key=None,
                now=NOW + timedelta(microseconds=1),
            )
            await TaskRouter().route(
                session,
                task_id=second.task_id,
                now=NOW + timedelta(microseconds=1),
            )
            await session.commit()

        async with self.database.session_factory() as session:
            leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=2,
                ),
                now=NOW + timedelta(seconds=1),
            )
            await session.commit()

        self.assertEqual(len(leases), 2)
        self.assertEqual(
            {lease.device_id for lease in leases},
            {"cuda-0", "cuda-1"},
        )
        self.assertEqual(leases[0].device_id, "cuda-1")
        self.assertTrue(all(lease.runtime is DeviceRuntime.CUDA for lease in leases))

    async def test_lease_respects_worker_reported_mime_capability(self) -> None:
        await self.prepare_routed_task()
        async with self.database.session_factory() as session:
            worker = await self.workers.get(session, WORKER_ID)
            self.assertIsNotNone(worker)
            if worker is not None:
                incompatible = capability().model_copy(
                    update={"mime_types": ["application/json"]}
                )
                worker.backends_payload = [incompatible.model_dump(mode="json")]
            await session.commit()

        async with self.database.session_factory() as session:
            leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW,
            )

        self.assertEqual(leases, [])

    async def test_lease_prefers_higher_weight_compatible_worker(self) -> None:
        await self.prepare_routed_task()
        lower_worker_id = "worker_lowerweight"
        async with self.database.session_factory() as session:
            await self.workers.register(
                session,
                request=registration().model_copy(
                    update={
                        "worker_id": lower_worker_id,
                        "name": "Lower Weight Worker",
                        "hostname": "worker-02",
                    }
                ),
                now=NOW,
            )
            await self.workers.update(
                session,
                worker_id=WORKER_ID,
                update=UpdateWorkerRequest(scheduling_weight=200),
                now=NOW,
            )
            await self.workers.update(
                session,
                worker_id=lower_worker_id,
                update=UpdateWorkerRequest(scheduling_weight=50),
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            lower_leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=lower_worker_id,
                    available_slots=1,
                ),
                now=NOW,
            )
            await session.commit()
        self.assertEqual(lower_leases, [])

        async with self.database.session_factory() as session:
            preferred_leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW,
            )
            await session.commit()
        self.assertEqual(len(preferred_leases), 1)

    async def test_preferred_gpu_runtime_uses_cpu_only_as_fallback(self) -> None:
        await self.prepare_routed_task(
            backend_runtimes=[DeviceRuntime.CUDA, DeviceRuntime.CPU],
            preferred_runtimes=[DeviceRuntime.CUDA],
        )

        async with self.database.session_factory() as session:
            cpu_fallback = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW,
            )
            await session.rollback()
        self.assertEqual(len(cpu_fallback), 1)
        self.assertEqual(cpu_fallback[0].runtime, DeviceRuntime.CPU)

        cuda_worker_id = "worker_cudaprefer"
        async with self.database.session_factory() as session:
            await self.workers.register(
                session,
                request=registration(
                    worker_id=cuda_worker_id,
                    runtime=DeviceRuntime.CUDA,
                ),
                now=NOW,
            )
            await self.workers.update(
                session,
                worker_id=WORKER_ID,
                update=UpdateWorkerRequest(scheduling_weight=1000),
                now=NOW,
            )
            await self.workers.update(
                session,
                worker_id=cuda_worker_id,
                update=UpdateWorkerRequest(scheduling_weight=1),
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            cpu_leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW,
            )
            await session.commit()
        self.assertEqual(cpu_leases, [])

        async with self.database.session_factory() as session:
            cuda_leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=cuda_worker_id,
                    available_slots=1,
                ),
                now=NOW,
            )
            await session.commit()
        self.assertEqual(len(cuda_leases), 1)
        self.assertEqual(cuda_leases[0].runtime, DeviceRuntime.CUDA)

    async def test_live_device_load_can_outweigh_equal_worker_weight(self) -> None:
        await self.prepare_routed_task()
        idle_worker_id = "worker_idleworker"
        async with self.database.session_factory() as session:
            await self.workers.register(
                session,
                request=registration().model_copy(
                    update={
                        "worker_id": idle_worker_id,
                        "name": "Idle Worker",
                        "hostname": "worker-03",
                    }
                ),
                now=NOW,
            )
            for sequence, worker_id, utilization in (
                (1, WORKER_ID, 95.0),
                (1, idle_worker_id, 10.0),
            ):
                await self.workers.heartbeat(
                    session,
                    request=WorkerHeartbeatRequest(
                        worker_id=worker_id,
                        sequence=sequence,
                        status=WorkerStatus.ONLINE,
                        resources=WorkerResourceUsage(
                            cpu_percent=utilization,
                            memory_used_bytes=int(utilization * 10),
                            memory_total_bytes=1000,
                            running_tasks=0,
                            leased_tasks=0,
                        ),
                        devices=[
                            DeviceUsage(
                                device_id="cpu-0",
                                utilization_percent=utilization,
                                memory_used_bytes=int(utilization * 10),
                                memory_total_bytes=1000,
                            )
                        ],
                        timestamp=NOW,
                    ),
                    now=NOW,
                )
            await session.commit()

        async with self.database.session_factory() as session:
            busy_leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=WORKER_ID,
                    available_slots=1,
                ),
                now=NOW,
            )
            await session.commit()
        self.assertEqual(busy_leases, [])

        async with self.database.session_factory() as session:
            idle_leases = await self.scheduler.lease(
                session,
                request=WorkerLeaseRequest(
                    worker_id=idle_worker_id,
                    available_slots=1,
                ),
                now=NOW,
            )
            await session.commit()
        self.assertEqual(len(idle_leases), 1)

    async def test_expired_lease_requeues_until_attempts_exhausted(self) -> None:
        task_id = await self.prepare_routed_task(maximum_attempts=2)
        async with self.database.session_factory() as session:
            first = (
                await self.scheduler.lease(
                    session,
                    request=WorkerLeaseRequest(
                        worker_id=WORKER_ID,
                        available_slots=1,
                    ),
                    now=NOW,
                )
            )[0]
            await session.commit()

        async with self.database.session_factory() as session:
            expired = await self.scheduler.requeue_expired(
                session,
                now=NOW + timedelta(seconds=31),
            )
            await session.commit()
        self.assertEqual(expired, [first.stage_id])

        async with self.database.session_factory() as session:
            second = (
                await self.scheduler.lease(
                    session,
                    request=WorkerLeaseRequest(
                        worker_id=WORKER_ID,
                        available_slots=1,
                    ),
                    now=NOW + timedelta(seconds=33),
                )
            )[0]
            await session.commit()
        self.assertEqual(second.attempt, 2)

        async with self.database.session_factory() as session:
            await self.scheduler.requeue_expired(
                session,
                now=NOW + timedelta(seconds=64),
            )
            await session.commit()
        async with self.database.session_factory() as session:
            task = await self.tasks.get(session, task_id)
        self.assertIsNotNone(task)
        if task is not None:
            self.assertEqual(task.status, TaskStatus.FAILED)

    async def test_failed_completion_is_idempotent_before_next_lease(self) -> None:
        await self.prepare_routed_task(maximum_attempts=2)
        async with self.database.session_factory() as session:
            lease = (
                await self.scheduler.lease(
                    session,
                    request=WorkerLeaseRequest(
                        worker_id=WORKER_ID,
                        available_slots=1,
                    ),
                    now=NOW,
                )
            )[0]
            await self.scheduler.start(
                session,
                stage_id=lease.stage_id,
                worker_id=WORKER_ID,
                lease_token=lease.lease_token,
                now=NOW + timedelta(seconds=1),
            )
            completion = CompleteStageRequest(
                worker_id=WORKER_ID,
                lease_token=lease.lease_token,
                status="failed",
                error=ErrorDetail(
                    code=ErrorCode.INTERNAL_ERROR,
                    message="transient failure",
                    retryable=True,
                ),
            )
            first = await self.scheduler.complete(
                session,
                stage_id=lease.stage_id,
                request=completion,
                now=NOW + timedelta(seconds=2),
            )
            replay = await self.scheduler.complete(
                session,
                stage_id=lease.stage_id,
                request=completion,
                now=NOW + timedelta(seconds=3),
            )
            await session.commit()

        self.assertIsNotNone(first)
        self.assertIsNotNone(replay)
        if first is not None and replay is not None:
            self.assertEqual(first.stage_status, StageStatus.PENDING)
            self.assertEqual(replay.stage_status, StageStatus.PENDING)
            self.assertEqual(first.task_status, replay.task_status)


if __name__ == "__main__":
    unittest.main()
