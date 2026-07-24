from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKER = ROOT / "docker"
VENDOR_PROFILES = {
    "cuda": ("nvidia", "CUDA_BASE_IMAGE"),
    "ascend": ("huawei", "ASCEND_BASE_IMAGE"),
    "mlu": ("cambricon", "MLU_BASE_IMAGE"),
    "dcu": ("hygon", "DCU_BASE_IMAGE"),
    "musa": ("moore_threads", "MUSA_BASE_IMAGE"),
    "xpu": ("kunlun", "XPU_BASE_IMAGE"),
}


class DockerfileContractTests(unittest.TestCase):
    def test_all_runtime_images_are_separate(self) -> None:
        expected = {
            "control-plane.Dockerfile",
            "web.Dockerfile",
            "worker-cpu.Dockerfile",
            *(f"worker-{runtime}.Dockerfile" for runtime in VENDOR_PROFILES),
        }
        self.assertTrue(expected.issubset({path.name for path in DOCKER.iterdir()}))

    def test_cpu_worker_contains_conversion_and_media_tools(self) -> None:
        contents = (DOCKER / "worker-cpu.Dockerfile").read_text()
        for package in (
            "ffmpeg",
            "libreoffice-calc",
            "libreoffice-impress",
            "libreoffice-writer",
            "fonts-noto-cjk",
            "util-linux",
        ):
            self.assertIn(package, contents)
        self.assertIn("--extra worker-cpu", contents)
        self.assertIn("PARSER_WORKER_DEVICE_RUNTIME=cpu", contents)
        self.assertIn(
            "PARSER_WORKER_SUBPROCESS_RESOURCE_LIMITS_REQUIRED=true",
            contents,
        )

    def test_control_plane_has_no_worker_or_hardware_profile(self) -> None:
        contents = (DOCKER / "control-plane.Dockerfile").read_text()
        self.assertIn("--extra control-plane", contents)
        self.assertNotIn("--extra worker-", contents)
        self.assertNotIn("libreoffice", contents.lower())
        self.assertNotIn("ffmpeg", contents.lower())

    def test_vendor_workers_require_independent_vendor_base_images(self) -> None:
        for runtime, (vendor, base_argument) in VENDOR_PROFILES.items():
            with self.subTest(runtime=runtime):
                contents = (DOCKER / f"worker-{runtime}.Dockerfile").read_text()
                self.assertIn(f"ARG {base_argument}\n", contents)
                self.assertIn(f"FROM ${{{base_argument}}}", contents)
                self.assertIn(f"--extra worker-{runtime}", contents)
                self.assertIn(
                    f"PARSER_WORKER_DEVICE_RUNTIME={runtime}",
                    contents,
                )
                self.assertIn(
                    f"PARSER_WORKER_DEVICE_VENDOR={vendor}",
                    contents,
                )
                self.assertNotIn("--extra worker-cpu", contents)
                if runtime != "cuda":
                    self.assertNotIn("CUDA_BASE_IMAGE", contents)

    def test_every_python_image_uses_frozen_production_sync(self) -> None:
        for path in DOCKER.glob("*.Dockerfile"):
            if path.name == "web.Dockerfile":
                continue
            with self.subTest(path=path.name):
                contents = path.read_text()
                self.assertIn("uv sync --frozen --no-dev", contents)
                self.assertIn("USER 10001", contents)

    def test_cuda_worker_requires_runtime_device_probe(self) -> None:
        contents = (DOCKER / "worker-cuda.Dockerfile").read_text()
        self.assertIn("PARSER_WORKER_DEVICE_PROBE_REQUIRED=true", contents)


class ComposeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contents = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    def test_compose_contains_shared_infrastructure_and_release_jobs(self) -> None:
        for service in (
            "postgres:",
            "redis:",
            "minio:",
            "minio-init:",
            "migrate:",
            "control-plane:",
            "catalog-init:",
            "web:",
            "worker-cpu:",
        ):
            self.assertIn(f"  {service}", self.contents)
        self.assertIn('alembic", "upgrade", "head', self.contents)
        self.assertIn("service_completed_successfully", self.contents)
        self.assertIn("PARSER_SERVE_TASK_QUEUE_BACKEND: redis_streams", self.contents)
        self.assertIn("PARSER_SERVE_STORAGE_BACKEND: s3", self.contents)

    def test_hardware_workers_use_separate_profiles_and_dockerfiles(self) -> None:
        for runtime in VENDOR_PROFILES:
            with self.subTest(runtime=runtime):
                self.assertIn(f"  worker-{runtime}:", self.contents)
                self.assertIn(f"profiles: [{runtime}]", self.contents)
                self.assertIn(
                    f"dockerfile: docker/worker-{runtime}.Dockerfile",
                    self.contents,
                )
        self.assertNotIn("profiles: [cpu]", self.contents)
        self.assertNotIn("privileged: true", self.contents)

    def test_web_nginx_proxies_api_and_disables_stream_buffering(self) -> None:
        contents = (DOCKER / "web-nginx.conf").read_text(encoding="utf-8")
        self.assertIn("proxy_pass http://control-plane:8000", contents)
        self.assertIn("(api|health|ready|metrics|mcp)", contents)
        self.assertIn("proxy_buffering off", contents)

    def test_real_environment_file_is_ignored_but_example_is_tracked(self) -> None:
        contents = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env\n", contents)
        self.assertIn("!.env.example", contents)
