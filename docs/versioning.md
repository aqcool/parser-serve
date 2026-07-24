# 版本与兼容策略

Parser Serve 分别维护应用版本、HTTP API 版本和解析结果 Schema 版本，三者
不能相互替代。

## 三类版本

- 应用版本使用 SemVer，例如 `0.1.0`，对应 Python 包、控制面和 Worker
  发布版本。
- HTTP API 版本使用 `major.minor`。URL 只包含主版本（当前 `/api/v1`），
  同一主版本内只允许向后兼容地增加可选字段、枚举能力或新接口。
- ParseResult Schema 使用独立的 `major.minor`，写入每一份结构化结果以及
  回调、MCP 和系统能力响应。

删除字段、改变字段含义、收紧既有合法输入或改变状态机语义，都需要提升对应
协议的主版本并提供迁移期。新增可选字段、新事件类型或新 Backend 能力通常
提升次版本。修复实现但不改变协议时只提升应用补丁版本。

## 单一来源

当前发布版本在 `pyproject.toml` 与 `Settings.app_version` 中保持一致。
`Settings.api_version` 和 `Settings.result_schema_version` 分别定义 HTTP 与
结果协议版本。发布流程修改版本后必须重新导出 `web/openapi.json`，并通过
OpenAPI 快照测试。

## 构建追溯

控制面通过以下部署变量接收不可变构建元数据：

```dotenv
PARSER_SERVE_BUILD_COMMIT=abcdef123456
PARSER_SERVE_BUILD_TIME=2026-07-24T10:30:00Z
```

`GET /api/v1/system/info` 使用普通 API Key 返回应用、API、结果 Schema、
Git 提交和 UTC 构建时间。控制面 Dockerfile 同时接受 `BUILD_COMMIT` 与
`BUILD_TIME` Build Args，并写入 OCI revision/created Label 和上述运行环境
变量。未注入时两个字段明确返回 `null`，不伪造版本来源。

## 发布检查

每次版本发布至少执行：

```bash
uv lock --check
uv run ruff format --check parser_serve tests migrations scripts
uv run ruff check parser_serve tests migrations scripts
uv run pyright parser_serve
uv run pytest --cov=parser_serve
uv run python -m scripts.export_openapi
git diff --exit-code -- web/openapi.json
```

CI 在 Python 3.12 和 3.13 上执行相同门禁，覆盖率不得低于 80%。镜像构建、
真实 PostgreSQL/Redis/MinIO、硬件和模型端到端验证属于后续发布流水线，
不由当前纯代码 CI 虚假替代。
