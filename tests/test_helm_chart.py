from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "parser-serve"


class HelmChartContractTests(unittest.TestCase):
    def test_chart_and_values_define_every_hardware_profile(self) -> None:
        chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
        values = yaml.safe_load((CHART / "values.yaml").read_text())

        self.assertEqual(chart["apiVersion"], "v2")
        self.assertEqual(chart["type"], "application")
        expected = {"cpu", "cuda", "ascend", "mlu", "dcu", "musa", "xpu"}
        self.assertEqual(set(values["workers"]), expected)
        self.assertTrue(values["workers"]["cpu"]["enabled"])
        for runtime, worker in values["workers"].items():
            self.assertEqual(worker["runtime"], runtime)
            self.assertEqual(
                worker["nodeSelector"]["parser-serve/runtime"],
                runtime,
            )
            self.assertEqual(
                worker["image"]["repository"],
                f"parser-worker-{runtime}",
            )

    def test_accelerator_profiles_declare_vendor_resources(self) -> None:
        values = yaml.safe_load((CHART / "values.yaml").read_text())
        resource_names = {
            "cuda": "nvidia.com/gpu",
            "ascend": "huawei.com/Ascend910",
            "mlu": "cambricon.com/mlu",
            "dcu": "hygon.com/dcu",
            "musa": "mthreads.com/vgpu",
            "xpu": "kunlunxin.com/xpu",
        }
        for runtime, resource_name in resource_names.items():
            with self.subTest(runtime=runtime):
                resources = values["workers"][runtime]["resources"]
                self.assertEqual(resources["requests"][resource_name], "1")
                self.assertEqual(resources["limits"][resource_name], "1")

    def test_templates_enforce_migration_and_graceful_worker_rollout(self) -> None:
        migration = (CHART / "templates" / "migration-job.yaml").read_text()
        workers = (CHART / "templates" / "workers.yaml").read_text()
        control = (CHART / "templates" / "control-plane.yaml").read_text()

        self.assertIn("pre-install,pre-upgrade", migration)
        self.assertIn('command: ["alembic", "upgrade", "head"]', migration)
        self.assertIn("terminationGracePeriodSeconds", workers)
        self.assertIn("maxUnavailable: 0", workers)
        self.assertIn("PARSER_WORKER_DEVICE_RUNTIME", workers)
        self.assertIn("PARSER_WORKER_ENGINE_BACKENDS", workers)
        self.assertIn("PARSER_WORKER_SUBPROCESS_MAXIMUM_MEMORY_BYTES", workers)
        self.assertTrue(
            yaml.safe_load((CHART / "values.yaml").read_text())["workerDefaults"][
                "subprocessResourceLimitsRequired"
            ]
        )
        self.assertIn("readOnlyRootFilesystem: true", control)
        self.assertNotIn(
            "kind: Secret",
            "\n".join(
                path.read_text()
                for path in (CHART / "templates").iterdir()
                if path.is_file()
            ),
        )

    def test_network_policies_isolate_worker_and_internal_api(self) -> None:
        values = yaml.safe_load((CHART / "values.yaml").read_text())
        policies = (CHART / "templates" / "network-policies.yaml").read_text()

        self.assertFalse(values["networkPolicy"]["enabled"])
        self.assertIn("kind: NetworkPolicy", policies)
        self.assertEqual(policies.count("kind: NetworkPolicy"), 3)
        self.assertIn("app.kubernetes.io/component: worker", policies)
        self.assertIn("ingress: []", policies)
        self.assertIn("app.kubernetes.io/component: control-plane", policies)
        self.assertIn("app.kubernetes.io/component: web", policies)
        self.assertIn("ipv4Except", policies)
        self.assertIn("ipv6Except", policies)
        self.assertIn("additionalEgress", policies)
        self.assertIn("port: 8000", policies)

    def test_monitoring_uses_authenticated_scrapes_and_actionable_rules(self) -> None:
        values = yaml.safe_load((CHART / "values.yaml").read_text())
        monitoring = (CHART / "templates" / "monitoring.yaml").read_text()

        self.assertFalse(values["monitoring"]["serviceMonitor"]["enabled"])
        self.assertFalse(values["monitoring"]["prometheusRule"]["enabled"])
        self.assertIn("kind: ServiceMonitor", monitoring)
        self.assertIn("authorization:", monitoring)
        self.assertIn("type: Bearer", monitoring)
        self.assertIn("kind: PrometheusRule", monitoring)
        for alert in (
            "ParserServeControlPlaneDown",
            "ParserServeNoOnlineWorkers",
            "ParserServeHighServerErrorRatio",
            "ParserServePendingTaskBacklog",
            "ParserServeRetryWaitStageBacklog",
            "ParserServeWorkerSaturation",
            "ParserServeCallbackFailures",
        ):
            self.assertIn(f"alert: {alert}", monitoring)
        self.assertNotIn("sum(parser_task_records", monitoring)


if __name__ == "__main__":
    unittest.main()
