from __future__ import annotations

import json
import subprocess
import unittest
from collections.abc import Sequence
from unittest.mock import patch

from pydantic import SecretStr

from parser_serve.schema.hardware import (
    DeviceRuntime,
    HardwareProbeSnapshot,
    HardwareVendor,
)
from parser_serve.worker.config import WorkerSettings
from parser_serve.worker.hardware import (
    HardwareProbe,
    HardwareProbeError,
    nvidia_devices,
    nvidia_usage,
    run_probe_command,
)


def settings(**updates: object) -> WorkerSettings:
    return WorkerSettings.model_validate(
        {
            "api_key": SecretStr(f"parser_{'h' * 32}"),
            "worker_id": "worker_hardware1",
            **updates,
        }
    )


class HardwareProbeSchemaTests(unittest.TestCase):
    def test_rejects_unknown_and_duplicate_usage_devices(self) -> None:
        base = {
            "schema_version": "1.0",
            "devices": [
                {
                    "device_id": "cpu-0",
                    "vendor": "generic",
                    "runtime": "cpu",
                    "model": "CPU",
                    "total_memory_bytes": 1024,
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "detected device"):
            HardwareProbeSnapshot.model_validate(
                {
                    **base,
                    "usage": [
                        {
                            "device_id": "cpu-1",
                            "memory_used_bytes": 0,
                            "memory_total_bytes": 1024,
                        }
                    ],
                }
            )
        with self.assertRaisesRegex(ValueError, "must be unique"):
            HardwareProbeSnapshot.model_validate(
                {
                    **base,
                    "usage": [
                        {"device_id": "cpu-0"},
                        {"device_id": "cpu-0"},
                    ],
                }
            )


class NvidiaProbeTests(unittest.TestCase):
    def test_parses_multiple_devices_and_usage(self) -> None:
        def runner(arguments: Sequence[str], timeout: float) -> str:
            self.assertEqual(timeout, 3.0)
            query = next(item for item in arguments if item.startswith("--query-gpu"))
            if "utilization.gpu" in query:
                return "0, 42, 1024, 24576, 61\n1, 3, 256, 24576, 40\n"
            return "0, NVIDIA A10, 24576, 555.42\n1, NVIDIA A10, 24576, 555.42\n"

        devices = nvidia_devices(runner=runner, timeout_seconds=3.0)
        usage = nvidia_usage(runner=runner, timeout_seconds=3.0)

        self.assertEqual([item.device_id for item in devices], ["cuda-0", "cuda-1"])
        self.assertEqual(devices[0].total_memory_bytes, 24576 * 1024 * 1024)
        self.assertEqual(usage[0].utilization_percent, 42.0)
        self.assertEqual(usage[0].temperature_celsius, 61.0)

    def test_rejects_malformed_or_non_numeric_nvidia_output(self) -> None:
        with self.assertRaisesRegex(HardwareProbeError, "malformed CSV"):
            nvidia_devices(runner=lambda _arguments, _timeout: "0, only-two")
        with self.assertRaisesRegex(HardwareProbeError, "invalid usage"):
            nvidia_usage(runner=lambda _arguments, _timeout: "0, unknown, 1, 2, 30")


class VendorProbeCommandTests(unittest.TestCase):
    def test_accepts_strict_snapshot_for_every_runtime_vendor_pair(self) -> None:
        pairs = (
            (DeviceRuntime.CUDA, HardwareVendor.NVIDIA),
            (DeviceRuntime.ASCEND, HardwareVendor.HUAWEI),
            (DeviceRuntime.MLU, HardwareVendor.CAMBRICON),
            (DeviceRuntime.DCU, HardwareVendor.HYGON),
            (DeviceRuntime.MUSA, HardwareVendor.MOORE_THREADS),
            (DeviceRuntime.XPU, HardwareVendor.KUNLUN),
        )
        for runtime, vendor in pairs:
            with self.subTest(runtime=runtime):
                payload = json.dumps(
                    {
                        "schema_version": "1.0",
                        "devices": [
                            {
                                "device_id": f"{runtime.value}-0",
                                "vendor": vendor.value,
                                "runtime": runtime.value,
                                "model": "Test Accelerator",
                                "total_memory_bytes": 16 * 1024**3,
                                "driver_version": "1.2.3",
                                "runtime_version": "4.5.6",
                            }
                        ],
                        "usage": [
                            {
                                "device_id": f"{runtime.value}-0",
                                "utilization_percent": 25.0,
                                "memory_used_bytes": 1024,
                                "memory_total_bytes": 16 * 1024**3,
                                "temperature_celsius": 48.0,
                            }
                        ],
                    }
                )
                probe = HardwareProbe(
                    settings(
                        device_runtime=runtime,
                        device_vendor=vendor,
                        device_probe_command=["vendor-probe", "--json"],
                        device_probe_required=True,
                    ),
                    runner=lambda arguments, timeout, output=payload: output,
                )

                self.assertEqual(probe.devices[0].runtime, runtime)
                self.assertEqual(probe.devices[0].vendor, vendor)
                self.assertEqual(probe.sample_usage()[0].utilization_percent, 25.0)

    def test_rejects_wrong_runtime_oversized_and_invalid_output(self) -> None:
        wrong_runtime = json.dumps(
            {
                "schema_version": "1.0",
                "devices": [
                    {
                        "device_id": "cpu-0",
                        "vendor": "generic",
                        "runtime": "cpu",
                        "model": "CPU",
                    }
                ],
            }
        )
        required = settings(
            device_runtime=DeviceRuntime.CUDA,
            device_vendor=HardwareVendor.NVIDIA,
            device_probe_command=["probe"],
            device_probe_required=True,
        )
        with self.assertRaisesRegex(HardwareProbeError, "outside Worker"):
            HardwareProbe(required, runner=lambda _arguments, _timeout: wrong_runtime)
        with self.assertRaisesRegex(HardwareProbeError, "does not match"):
            HardwareProbe(required, runner=lambda _arguments, _timeout: "{}")

        limited = settings(
            device_probe_command=["probe"],
            device_probe_required=True,
            device_probe_maximum_output_bytes=1024,
        )
        with self.assertRaisesRegex(HardwareProbeError, "exceeds"):
            HardwareProbe(limited, runner=lambda _arguments, _timeout: " " * 1025)

    def test_optional_probe_falls_back_but_required_probe_fails(self) -> None:
        def unavailable(_arguments: Sequence[str], _timeout: float) -> str:
            raise HardwareProbeError("missing")

        optional = HardwareProbe(
            settings(
                device_runtime=DeviceRuntime.CUDA,
                device_vendor=HardwareVendor.NVIDIA,
            ),
            runner=unavailable,
        )
        self.assertEqual(optional.devices[0].device_id, "cpu-0")
        self.assertEqual(optional.devices[0].runtime, DeviceRuntime.CUDA)

        with self.assertRaisesRegex(HardwareProbeError, "missing"):
            HardwareProbe(
                settings(
                    device_runtime=DeviceRuntime.CUDA,
                    device_vendor=HardwareVendor.NVIDIA,
                    device_probe_required=True,
                ),
                runner=unavailable,
            )

    def test_command_runner_never_uses_a_shell_and_maps_failures(self) -> None:
        completed = subprocess.CompletedProcess(
            ["probe", "--json"],
            returncode=0,
            stdout='{"schema_version":"1.0"}',
            stderr="",
        )
        with patch(
            "parser_serve.worker.hardware.subprocess.run",
            return_value=completed,
        ) as mocked:
            output = run_probe_command(["probe", "--json"], 2.0)
        self.assertEqual(output, completed.stdout)
        self.assertFalse(mocked.call_args.kwargs.get("shell", False))

        failed = subprocess.CompletedProcess(
            ["probe"],
            returncode=7,
            stdout="",
            stderr="failure",
        )
        with (
            patch(
                "parser_serve.worker.hardware.subprocess.run",
                return_value=failed,
            ),
            self.assertRaisesRegex(HardwareProbeError, "status 7"),
        ):
            run_probe_command(["probe"], 2.0)


if __name__ == "__main__":
    unittest.main()
