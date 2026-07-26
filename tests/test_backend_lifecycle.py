from __future__ import annotations

import asyncio
import unittest

from parser_serve.backends import (
    BackendContext,
    BackendExecutionError,
    BackendOutput,
    BackendRegistry,
)
from parser_serve.schema.backend import BackendCapability, BackendLoadTarget
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.hardware import DeviceRuntime


class LifecycleBackend:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail_load: bool = False,
        fail_unload: bool = False,
    ) -> None:
        self.capability = BackendCapability(
            name=name,
            version="1.0",
            media_categories=[MediaCategory.TEXT],
            runtimes=[DeviceRuntime.CUDA],
            maximum_concurrency=1,
        )
        self.events = events
        self.fail_load = fail_load
        self.fail_unload = fail_unload

    async def load(self) -> None:
        self.events.append(f"load:{self.capability.name}")
        if self.fail_load:
            raise RuntimeError("model allocation failed")

    async def unload(self) -> None:
        self.events.append(f"unload:{self.capability.name}")
        if self.fail_unload:
            raise RuntimeError("model release failed")

    async def execute(self, context: BackendContext) -> BackendOutput:
        raise AssertionError("lifecycle tests do not execute inference")


def target(name: str) -> BackendLoadTarget:
    return BackendLoadTarget(name=name, version="1.0")


class BackendLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_preload_is_idempotent_and_unload_uses_reverse_order(self) -> None:
        events: list[str] = []
        registry = BackendRegistry()
        registry.register(LifecycleBackend("model_a", events))
        registry.register(LifecycleBackend("model_b", events))

        await registry.preload([target("model_a"), target("model_b")])
        await registry.preload([target("model_a")])
        self.assertEqual(
            registry.loaded_backends,
            (target("model_a"), target("model_b")),
        )

        await registry.unload_all()

        self.assertEqual(
            events,
            [
                "load:model_a",
                "load:model_b",
                "unload:model_b",
                "unload:model_a",
            ],
        )
        self.assertEqual(registry.loaded_backends, ())

    async def test_failed_batch_rolls_back_models_loaded_by_that_batch(self) -> None:
        events: list[str] = []
        registry = BackendRegistry()
        registry.register(LifecycleBackend("model_a", events))
        registry.register(LifecycleBackend("model_b", events, fail_load=True))

        with self.assertRaisesRegex(BackendExecutionError, "model preload failed"):
            await registry.preload([target("model_a"), target("model_b")])

        self.assertEqual(
            events,
            ["load:model_a", "load:model_b", "unload:model_a"],
        )
        self.assertEqual(registry.loaded_backends, ())

    async def test_cancelled_batch_rolls_back_models_loaded_by_that_batch(self) -> None:
        class CancelledBackend(LifecycleBackend):
            async def load(self) -> None:
                self.events.append(f"load:{self.capability.name}")
                raise asyncio.CancelledError

        events: list[str] = []
        registry = BackendRegistry()
        registry.register(LifecycleBackend("model_a", events))
        registry.register(CancelledBackend("model_b", events))

        with self.assertRaises(asyncio.CancelledError):
            await registry.preload([target("model_a"), target("model_b")])

        self.assertEqual(
            events,
            ["load:model_a", "load:model_b", "unload:model_a"],
        )
        self.assertEqual(registry.loaded_backends, ())

    async def test_rejects_unmanaged_or_missing_backend(self) -> None:
        class UnmanagedBackend:
            capability = BackendCapability(
                name="stateless",
                version="1.0",
                media_categories=[MediaCategory.TEXT],
                runtimes=[DeviceRuntime.CPU],
                maximum_concurrency=1,
            )

            async def execute(self, context: BackendContext) -> BackendOutput:
                raise AssertionError

        registry = BackendRegistry()
        registry.register(UnmanagedBackend())

        with self.assertRaisesRegex(
            BackendExecutionError, "does not support model preloading"
        ):
            await registry.preload([target("stateless")])
        with self.assertRaisesRegex(BackendExecutionError, "is not installed"):
            await registry.preload([target("missing")])

    async def test_unload_attempts_all_models_and_retains_failed_state(self) -> None:
        events: list[str] = []
        registry = BackendRegistry()
        registry.register(LifecycleBackend("model_a", events, fail_unload=True))
        registry.register(LifecycleBackend("model_b", events))
        await registry.preload([target("model_a"), target("model_b")])

        with self.assertRaisesRegex(BackendExecutionError, "model_a@1.0"):
            await registry.unload_all()

        self.assertEqual(registry.loaded_backends, (target("model_a"),))
        self.assertEqual(events[-2:], ["unload:model_b", "unload:model_a"])


if __name__ == "__main__":
    unittest.main()
