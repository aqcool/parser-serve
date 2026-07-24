# Python SDK

Python SDK 复用 `parser_serve.schema` 中的 Pydantic 类型，并从提交到仓库的
OpenAPI 快照生成全部 operationId、HTTP 方法和路径。SDK 不复制服务端模型，
因此字段约束、枚举和错误响应与 HTTP API 使用同一份契约。

## 安装

只作为外部 Python 客户端使用时安装：

```bash
uv sync --frozen --no-dev --extra python-sdk
```

`python-sdk` 只增加 `httpx`。完整控制面和各 Worker Profile 已经包含
`httpx`，无需重复组合该 Profile。

## 同步客户端

```python
from parser_serve.schema.source import TextSource
from parser_serve.schema.task import CreateTaskRequest, TaskListQuery
from parser_serve.sdk import ParserServeClient

with ParserServeClient(
    "https://parser.example.com",
    api_key,
) as client:
    created = client.create_task(
        CreateTaskRequest(
            source=TextSource(type="text", text="需要解析的内容"),
        ),
        idempotency_key="business-order-42",
    )
    task = client.get_task(created.task_id)
    tasks = client.list_tasks(TaskListQuery(statuses=[task.status]))
```

API Key 只写入 `Authorization: Bearer` Header，不进入 URL。调用方不得记录
Client 构造参数或完整请求 Header。

## 异步客户端

```python
from parser_serve.sdk import AsyncParserServeClient

async with AsyncParserServeClient(
    "https://parser.example.com",
    api_key,
) as client:
    health = await client.health()
    uploaded = await client.upload_file(
        "sample.pdf",
        pdf_bytes,
        "application/pdf",
    )
```

同步和异步客户端都可通过 `client=` 复用调用方已有的 `httpx.Client` 或
`httpx.AsyncClient`。SDK 不会关闭外部传入的 Client；由 SDK 自己创建的
Client 会在上下文退出时关闭。

## 完整 operationId 调用

常用方法提供直接的 Pydantic 返回类型。其余管理、Worker、SSE 和下载接口可
通过生成的 operationId 使用 `request`、`request_raw` 或 `stream`：

```python
from pydantic import TypeAdapter

from parser_serve.schema.backend import BackendListResponse

response = client.request(
    "list_backends",
    TypeAdapter(BackendListResponse),
    query={"statuses": ["enabled"], "limit": 50},
)

with client.stream(
    "download_uploaded_file",
    path={"file_id": uploaded.file_id},
) as response:
    for chunk in response.iter_bytes():
        consume(chunk)
```

列表查询中的序列会编码成重复参数，例如
`statuses=pending&statuses=failed`。路径参数使用 URL 编码；缺少必填路径参数
会在发出网络请求前失败。SDK 拒绝调用方通过额外 Header 覆盖
`Authorization`。

非 2xx 响应抛出 `ParserServeApiError`。当服务端返回规范错误体时，可读取
`status_code`、`code`、`retryable`、`request_id` 和完整 `detail`。未知或非
JSON 网关错误仍保留 HTTP 状态，但 `code` 为 `None`，调用方不能把它误判为
可重试。

## 契约更新

后端 OpenAPI 变化后依次执行：

```bash
uv run python -m scripts.export_openapi
uv run python -m scripts.generate_python_sdk
uv run python -m scripts.generate_typescript_sdk
```

检查生成文件未漂移：

```bash
uv run python -m scripts.generate_python_sdk --check
```

CI 会校验生成表覆盖 OpenAPI 中全部唯一 operationId，并运行同步传输测试和
连接真实 FastAPI ASGI 应用的异步端到端测试。
