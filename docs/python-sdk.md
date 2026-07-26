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

常用方法提供直接的 Pydantic 返回类型。OpenAPI 中的每个 operation 还会生成
`call_<operation_id>` 同步和异步方法，以及独立的 Path、Query、Headers、
Body、Response wire type。管理、Worker、上传、SSE 和下载接口都不需要退回
无类型调用。例如：

```python
response = client.call_list_backends(
    query={"statuses": ["enabled"], "limit": 50},
)

content = client.call_download_uploaded_file(
    path={"file_id": uploaded.file_id},
)

for chunk in client.call_stream_events(
    query={"limit": 100},
    headers={"Last-Event-ID": last_event_id},
):
    consume(chunk)
```

例如 `call_get_task` 的参数是 `GetTaskPath`、`GetTaskQuery`、
`GetTaskHeaders` 和 `GetTaskBody`，返回 `GetTaskResponse`。这些类型与方法均由
OpenAPI 生成；新增接口如果没有同步生成，会在 CI 防漂移检查中失败。

底层 `request`、`request_raw` 和 `stream` 仍然公开，用于需要直接处理 HTTP
Response 的高级场景。

列表查询中的序列会编码成重复参数，例如
`statuses=pending&statuses=failed`。路径参数使用 URL 编码；缺少必填路径参数
会在发出网络请求前失败。SDK 拒绝调用方通过额外 Header 覆盖
`Authorization`。

非 2xx 响应抛出 `ParserServeApiError`。当服务端返回规范错误体时，可读取
`status_code`、`code`、`retryable`、`request_id` 和完整 `detail`。SDK 对新增
错误码向前兼容：未知 `code` 以字符串保留，同时继续保留消息、重试标记和
Request ID。只有未知或非 JSON 网关错误的 `code` 才为 `None`，调用方不能把
它误判为可重试。

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
