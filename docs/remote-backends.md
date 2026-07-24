# 远程 Backend 接入协议

## 1. 适用范围

远程协议用于把独立部署的 MinerU、PaddleOCR、PaddleOCR-VL、
HunyuanOCR、ASR 和 VLM 服务接入 Parser Serve。模型服务可以使用任意语言
和推理框架，只需通过一个轻量网关实现本文的 `1.0` 协议。

远程服务仍由 Worker 调用，而不是由控制面直接调用，因此：

- 调度、租约、重试和 Artifact 上传继续使用统一 Worker 流程。
- API Key、模型服务密钥和厂商 SDK 不进入控制面。
- 同一个服务可以在 CPU、CUDA 或国产硬件 Worker 中声明对应 Runtime。
- Worker 总并发和 Backend `maximum_concurrency` 会同时生效。

Pydantic 权威类型位于 `parser_serve/schema/remote.py`，执行实现位于
`parser_serve/backends/remote.py`。

## 2. Worker 配置

`PARSER_WORKER_REMOTE_BACKENDS` 是 `RemoteBackendConfig` 数组的 JSON：

```json
[
  {
    "name": "paddleocr",
    "version": "1.0",
    "endpoint": "http://paddleocr:8080/v1/parse",
    "authentication": {
      "type": "bearer",
      "token": "replace-with-service-token"
    },
    "media_categories": ["image"],
    "mime_types": ["image/*"],
    "maximum_concurrency": 2,
    "timeout_seconds": 300.0,
    "maximum_response_bytes": 67108864,
    "maximum_artifacts": 100,
    "maximum_artifact_bytes": 33554432
  }
]
```

可用认证类型：

| 类型 | 请求 Header |
| --- | --- |
| `none` | 不发送凭证 |
| `bearer` | `Authorization: Bearer <token>` |
| `x_api_key` | `X-API-Key: <token>` |

认证 Token 使用 `SecretStr`，不会出现在配置对象的日志表示中。Worker 禁止
跟随重定向，以免认证 Header 被转发到意外地址。Endpoint 属于受信任的运维
配置；生产环境仍应使用网络策略限制 Worker 只能访问批准的模型服务。

Backend 名称应与默认 Pipeline 约定一致：

| 能力 | 推荐 Backend 名称 |
| --- | --- |
| MinerU | `mineru` |
| PaddleOCR | `paddleocr` |
| PaddleOCR-VL | `paddleocr_vl` |
| HunyuanOCR | `hunyuan_ocr` |
| 语音识别 | `asr` |
| 通用图像 VLM | `vlm` |
| 视频 VLM | `video_vlm` |
| 动态网页渲染 | `web_rendered` |

同一 Worker 内 `(name, version)` 必须唯一，也不能与内置 Backend 冲突。

对于上述标准引擎，优先使用 `PARSER_WORKER_ENGINE_BACKENDS` 的类型化预设，
只需指定 `engine`、Endpoint、认证和执行限制，Worker 会自动补齐名称与能力。
需要接入其他自定义服务时再使用通用 `PARSER_WORKER_REMOTE_BACKENDS`。
配置示例见[解析引擎接入](engine-backends.md)。

## 3. 控制面 Backend 注册

Worker 上报的是“本机实际可执行能力”，控制面的 Backend Registry 是
Pipeline 使用的逻辑定义。两端的名称、版本、媒体类型和 Runtime 必须一致。
例如注册 CUDA PaddleOCR：

```http
POST /api/v1/management/backends
Authorization: Bearer <普通 API Key>
Content-Type: application/json

{
  "capability": {
    "name": "paddleocr",
    "version": "1.0",
    "media_categories": ["image"],
    "mime_types": ["image/*"],
    "runtimes": ["cuda"],
    "maximum_concurrency": 2
  },
  "execution_mode": "local",
  "default_timeout_seconds": 300,
  "maximum_attempts": 2
}
```

这里的 `execution_mode` 为 `local`，表示 Backend 由被租约选中的 Worker
执行；Worker 内部再调用模型服务。注册完成后重新调用
`POST /api/v1/management/defaults/initialize`，原先因缺少 Backend 而保持
Draft 的默认 Pipeline 会在校验通过后发布。

## 4. 请求协议

Worker 向配置的 Endpoint 发送 `POST multipart/form-data`：

- `request`：必选，Content-Type 为 `application/json`，内容符合
  `RemoteParseRequest`。
- `file`：文件 Source 时必选，按流上传；文本 Source 不包含此字段。

JSON 请求包含：

- 固定 `protocol_version: "1.0"`。
- Task、Stage、Backend 名称及版本。
- 本次调度确定的 Runtime。
- 本次调度确定的 `device_id`；跨节点 Ray Serve 可将它仅作为准入和追踪提示。
- 不可变 `SourceMetadata`。
- 文本内容，或文件名、MIME、字节数和 SHA-256。
- Pipeline Stage 参数和超时。

文件描述中的 SHA-256 由 Worker 在发送前计算。模型网关应同时验证 multipart
文件大小和摘要，不应仅信任 JSON。

## 5. 响应协议

成功响应使用 HTTP 2xx 和 `RemoteParseSucceeded`：

```json
{
  "status": "succeeded",
  "result": {
    "schema_version": "1.0",
    "task_id": "task_...",
    "source": {},
    "metadata": {},
    "blocks": [],
    "artifacts": [],
    "warnings": [],
    "created_at": "2026-07-24T12:00:00Z"
  },
  "artifacts": []
}
```

失败响应使用 `RemoteParseFailed`，建议搭配对应 HTTP 状态：

```json
{
  "status": "failed",
  "error": {
    "code": "DEPENDENCY_UNAVAILABLE",
    "message": "model is loading",
    "retryable": true,
    "field_violations": [],
    "context": {}
  }
}
```

响应 Content-Type 必须为 `application/json` 或
`application/problem+json`。Worker 对声明长度和实际流式读取长度都执行
限制；408、425、429、500、502、503、504 和网络/超时错误会映射为可重试
执行错误。

## 6. 结果约束

远程 `ParseResult` 必须满足：

- `task_id` 与请求完全一致。
- `source` 与请求的不可变 `SourceMetadata` 完全一致。
- `artifacts` 为空，因为最终 Artifact ID 和存储 URI 只能由控制面分配。
- 暂时不能返回引用未分配 Artifact ID 的 `ImageBlock` 或 `KeyframeBlock`。

响应顶层 `artifacts` 可携带 Base64 编码的辅助产物，Worker 会在验证数量、
单项大小和总大小后上传。当前这些辅助产物不能从 `ParseResult` Block 中
引用；带引用关系的二阶段 Artifact ID 回填属于后续协议版本。

这些限制不影响 OCR 文本、文档结构、表格、ASR 时间片和 VLM 文本描述。

需要用 Ray Serve 承载模型时，可直接使用仓库提供的协议 Ingress，见
[可选 Ray Serve Executor](ray-serve.md)。

## 7. 安全与可观测性

- 模型服务密钥只配置在 Worker。
- 不跟随 HTTP 重定向。
- 请求超时取 Stage 超时和 Backend 配置超时的较小值。
- 错误消息不会包含 Endpoint 或认证 Token。
- 响应必须先通过协议 Schema，再转换为 Worker Artifact。
- Backend 的并发上限由 Worker 信号量强制执行。
- 生产网络应配置服务发现、mTLS 或 Service Mesh、出口白名单和请求指标。
