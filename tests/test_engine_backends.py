from __future__ import annotations

import unittest

from pydantic import SecretStr, ValidationError

from parser_serve.backends import (
    ENGINE_CAPABILITY_PRESETS,
    EngineRemoteBackend,
    engine_remote_config,
)
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.engine import EngineBackendConfig, ParserEngine
from parser_serve.schema.hardware import DeviceRuntime, HardwareVendor
from parser_serve.worker import WorkerSettings
from parser_serve.worker.backends import configured_backend_registry


API_KEY = SecretStr(f"parser_{'e' * 32}")


class EngineBackendTests(unittest.TestCase):
    def config(self, engine: ParserEngine) -> EngineBackendConfig:
        return EngineBackendConfig.model_validate(
            {
                "engine": engine,
                "endpoint": f"http://{engine.value}.internal/v1/parse",
            }
        )

    def test_every_named_engine_has_a_canonical_remote_capability(self) -> None:
        expected_categories = {
            ParserEngine.PADDLEOCR: {MediaCategory.IMAGE, MediaCategory.DOCUMENT},
            ParserEngine.PADDLEOCR_VL: {
                MediaCategory.IMAGE,
                MediaCategory.DOCUMENT,
            },
            ParserEngine.HUNYUAN_OCR: {
                MediaCategory.IMAGE,
                MediaCategory.DOCUMENT,
            },
            ParserEngine.MINERU: {MediaCategory.DOCUMENT},
            ParserEngine.ASR: {MediaCategory.AUDIO},
            ParserEngine.VLM: {MediaCategory.IMAGE},
            ParserEngine.VIDEO_VLM: {MediaCategory.VIDEO},
            ParserEngine.WEB_RENDERED: {MediaCategory.WEB},
        }

        self.assertEqual(set(ENGINE_CAPABILITY_PRESETS), set(ParserEngine))
        for engine, categories in expected_categories.items():
            backend = EngineRemoteBackend(
                config=self.config(engine),
                runtime=DeviceRuntime.CPU,
            )
            self.assertEqual(backend.capability.name, engine.value)
            self.assertEqual(set(backend.capability.media_categories), categories)
            self.assertEqual(backend.capability.runtimes, [DeviceRuntime.CPU])
            self.assertEqual(
                engine_remote_config(self.config(engine)).name, engine.value
            )

    def test_worker_registers_engine_presets_from_typed_configuration(self) -> None:
        settings = WorkerSettings(
            api_key=API_KEY,
            worker_id="worker_engines12",
            engine_backends=[
                self.config(ParserEngine.PADDLEOCR),
                self.config(ParserEngine.MINERU),
                self.config(ParserEngine.ASR),
                self.config(ParserEngine.VIDEO_VLM),
                self.config(ParserEngine.WEB_RENDERED),
            ],
        )

        registry = configured_backend_registry(settings)
        names = {capability.name for capability in registry.capabilities}

        self.assertTrue(
            {
                "paddleocr",
                "mineru",
                "asr",
                "video_vlm",
                "web_rendered",
            }.issubset(names)
        )

    def test_cuda_worker_reports_engine_with_cuda_runtime(self) -> None:
        settings = WorkerSettings(
            api_key=API_KEY,
            worker_id="worker_cudaengine",
            device_runtime=DeviceRuntime.CUDA,
            device_vendor=HardwareVendor.NVIDIA,
            engine_backends=[self.config(ParserEngine.PADDLEOCR)],
        )

        registry = configured_backend_registry(settings)
        capability = registry.get("paddleocr", "1.0").capability

        self.assertEqual(capability.runtimes, [DeviceRuntime.CUDA])
        self.assertEqual(
            set(capability.media_categories),
            {MediaCategory.IMAGE, MediaCategory.DOCUMENT},
        )

    def test_engine_preset_is_runtime_neutral_for_domestic_accelerators(self) -> None:
        runtimes = {
            DeviceRuntime.ASCEND: HardwareVendor.HUAWEI,
            DeviceRuntime.MLU: HardwareVendor.CAMBRICON,
            DeviceRuntime.DCU: HardwareVendor.HYGON,
            DeviceRuntime.MUSA: HardwareVendor.MOORE_THREADS,
            DeviceRuntime.XPU: HardwareVendor.KUNLUN,
        }

        for runtime, vendor in runtimes.items():
            with self.subTest(runtime=runtime):
                settings = WorkerSettings(
                    api_key=API_KEY,
                    worker_id=f"worker_{runtime.value}engine",
                    device_runtime=runtime,
                    device_vendor=vendor,
                    engine_backends=[self.config(ParserEngine.PADDLEOCR)],
                )
                capability = (
                    configured_backend_registry(settings)
                    .get("paddleocr", "1.0")
                    .capability
                )
                self.assertEqual(capability.runtimes, [runtime])

    def test_generic_and_preset_backend_names_cannot_conflict(self) -> None:
        with self.assertRaises(ValidationError):
            WorkerSettings.model_validate(
                {
                    "api_key": API_KEY.get_secret_value(),
                    "worker_id": "worker_engines34",
                    "engine_backends": [
                        {
                            "engine": "paddleocr",
                            "endpoint": "http://paddle.internal/v1/parse",
                        }
                    ],
                    "remote_backends": [
                        {
                            "name": "paddleocr",
                            "endpoint": "http://other.internal/v1/parse",
                            "media_categories": ["image"],
                        }
                    ],
                }
            )

    def test_engine_endpoint_rejects_embedded_credentials(self) -> None:
        with self.assertRaises(ValidationError):
            EngineBackendConfig.model_validate(
                {
                    "engine": ParserEngine.HUNYUAN_OCR,
                    "endpoint": ("http://user:password@hunyuan.internal/v1/parse"),
                }
            )


if __name__ == "__main__":
    unittest.main()
