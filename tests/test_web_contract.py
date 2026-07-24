from __future__ import annotations

import unittest
from pathlib import Path

from parser_serve.api import create_app
from parser_serve.settings import Environment, Settings


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"


class WebManagementContractTests(unittest.TestCase):
    def test_management_client_targets_real_openapi_paths(self) -> None:
        schema = create_app(Settings(environment=Environment.TEST)).openapi()
        paths = set(schema["paths"])
        expected = {
            "/api/v1/management/backends",
            "/api/v1/management/backends/{backend_id}",
            "/api/v1/management/pipelines",
            ("/api/v1/management/pipelines/{pipeline_id}/versions/{version}/validate"),
            ("/api/v1/management/pipelines/{pipeline_id}/versions/{version}/test"),
            ("/api/v1/management/pipelines/{pipeline_id}/versions/{version}/publish"),
            "/api/v1/management/defaults/initialize",
            "/api/v1/management/callbacks",
            "/api/v1/management/callbacks/{delivery_id}/attempts",
            "/api/v1/management/callbacks/{delivery_id}/retry",
            "/api/v1/management/callbacks/test",
            "/api/v1/management/api-keys",
            "/api/v1/management/api-keys/{api_key_id}",
            "/api/v1/management/api-keys/{api_key_id}/rotate",
            "/api/v1/management/settings",
            "/api/v1/management/dashboard/summary",
            "/api/v1/management/maintenance/retention/run",
            "/api/v1/system/info",
        }
        self.assertTrue(expected.issubset(paths))

        client = (WEB / "api" / "client.ts").read_text(encoding="utf-8")
        generated = (WEB / "api" / "generated.ts").read_text(encoding="utf-8")
        for stable_prefix in (
            "/api/v1/management/backends",
            "/api/v1/management/pipelines",
            "/api/v1/management/defaults/initialize",
            "/api/v1/management/callbacks",
            "/api/v1/management/api-keys",
            "/api/v1/management/settings",
            "/api/v1/management/dashboard/summary",
            "/api/v1/management/maintenance/retention/run",
            "/api/v1/system/info",
        ):
            self.assertIn(stable_prefix, generated)
        self.assertIn('generatedRequest("get_dashboard_summary"', client)
        self.assertIn('generatedRequest("list_tasks"', client)
        self.assertIn('generatedRequest("get_task"', client)

        dashboard = (WEB / "views" / "DashboardView.vue").read_text(encoding="utf-8")
        self.assertIn("parserApi.dashboard", dashboard)
        self.assertIn("tasks.success_rate", dashboard)
        pipelines = (WEB / "views" / "management" / "PipelinesPanel.vue").read_text(
            encoding="utf-8"
        )
        self.assertIn("parserApi.testPipeline", pipelines)
        self.assertIn("创建测试任务", pipelines)
        system = (WEB / "views" / "management" / "SystemPanel.vue").read_text(
            encoding="utf-8"
        )
        self.assertIn("parserApi.runRetention", system)
        self.assertIn("试运行", system)
        worker_management = (WEB / "views" / "ManagementView.vue").read_text(
            encoding="utf-8"
        )
        self.assertIn("saveScheduling", worker_management)
        self.assertIn("scheduling_weight", worker_management)
        self.assertIn("health_checks", worker_management)

    def test_every_navigation_management_section_has_a_real_panel(self) -> None:
        management = (WEB / "views" / "ManagementView.vue").read_text(encoding="utf-8")
        self.assertNotIn("接口已就绪，页面实现中", management)
        for component in (
            "PipelinesPanel",
            "BackendsPanel",
            "CallbacksPanel",
            "ApiKeysPanel",
            "SystemPanel",
        ):
            self.assertIn(component, management)
            self.assertTrue(
                (WEB / "views" / "management" / f"{component}.vue").is_file()
            )

    def test_management_panels_do_not_embed_api_keys_in_urls(self) -> None:
        for path in (WEB / "views" / "management").glob("*.vue"):
            contents = path.read_text(encoding="utf-8")
            self.assertNotIn("api_key=", contents, path.name)
            self.assertNotIn("access_token=", contents, path.name)

    def test_parse_laboratory_covers_every_source_and_scheduling_contract(
        self,
    ) -> None:
        contents = (WEB / "views" / "ParseTestView.vue").read_text(encoding="utf-8")
        for source_type in ("text", "file", "url", "object_storage"):
            self.assertIn(f'"{source_type}"', contents)
        for option in (
            "pipeline_id",
            "pipeline_version",
            "backend_name",
            "strategy",
            "runtimes",
            "features",
            "client_reference",
        ):
            self.assertIn(option, contents)
        self.assertIn("<API_KEY>", contents)
        self.assertIn("navigator.clipboard.writeText", contents)

    def test_task_detail_uses_typed_result_artifact_and_sse_contracts(self) -> None:
        schema = create_app(Settings(environment=Environment.TEST)).openapi()
        paths = set(schema["paths"])
        expected = {
            "/api/v1/tasks/{task_id}",
            "/api/v1/tasks/{task_id}/stages",
            "/api/v1/tasks/{task_id}/result",
            "/api/v1/tasks/{task_id}/artifacts",
            "/api/v1/tasks/{task_id}/artifacts/{artifact_id}/content",
            "/api/v1/tasks/{task_id}/artifacts/{artifact_id}/download-url",
            "/api/v1/tasks/{task_id}/events/stream",
            "/api/v1/tasks/{task_id}/cancel",
            "/api/v1/tasks/{task_id}/retry",
        }
        self.assertTrue(expected.issubset(paths))

        client = (WEB / "api" / "client.ts").read_text(encoding="utf-8")
        detail = (WEB / "views" / "TaskDetailView.vue").read_text(encoding="utf-8")
        events = (WEB / "composables" / "useTaskEvents.ts").read_text(encoding="utf-8")
        router = (WEB / "router" / "index.ts").read_text(encoding="utf-8")

        generated = (WEB / "api" / "generated.ts").read_text(encoding="utf-8")
        for contract in ("StageDetail", "Artifact", "ParseResult", "TextBlock"):
            self.assertIn(f'"{contract}":', generated)
        for feature in (
            "taskStages",
            "taskArtifacts",
            "taskResult",
            "downloadArtifact",
            "cancelTask",
            "retryTask",
            "transcript",
            "keyframe",
            "application/pdf",
        ):
            self.assertIn(feature, detail + client)
        self.assertIn('path: "tasks/:taskId"', router)
        self.assertIn('headers.set("Last-Event-ID"', events)
        self.assertIn("Authorization:", events)
        self.assertNotIn("api_key=", events)
        self.assertNotIn("access_token=", events)
        self.assertNotIn("v-html", detail)
