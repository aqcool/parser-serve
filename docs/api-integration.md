# HTTP API 集成

parser-serve 的业务接口和开放管理接口都使用普通 API Key。系统不实现
RBAC；Worker 内部协议使用单独的 Worker API Key。

```http
Authorization: Bearer parser_xxx
Content-Type: application/json
```

API Key 不应放入 URL、日志或前端持久化存储。服务端响应均带
`X-Request-ID`，JSON 响应中的 `request_id` 与其一致，可用于跨系统排障。

## 创建和跟踪任务

创建文本任务：

```bash
curl -X POST http://localhost:8080/api/v1/tasks \
  -H "Authorization: Bearer $PARSER_SERVE_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-20260724-001" \
  -d '{
    "source": {
      "type": "text",
      "text": "需要解析的内容",
      "mime_type": "text/plain"
    },
    "options": {
      "features": {
        "extract_text": true,
        "extract_tables": true,
        "extract_images": false,
        "run_ocr": false,
        "generate_captions": false,
        "transcribe_audio": false,
        "extract_keyframes": false
      }
    },
    "client_reference": "order-20260724-001"
  }'
```

文件任务先通过 `POST /api/v1/files` 流式上传，再把返回的 `file_id` 放入
`source: {"type": "uploaded_file", "file_id": "..."}`。也可以提交 URL 或
S3/MinIO URI。调用方可轮询 `GET /api/v1/tasks/{task_id}`、订阅
`GET /api/v1/events/stream?task_id=...`，或在创建任务时提供带签名 Secret
的 Callback 配置。
Callback 是至少一次投递，接收方必须按稳定 Event ID 去重并验证 HMAC；完整
协议见[Callback 接入与幂等](callbacks.md)。

任务成功后，结构化结果位于 `GET /api/v1/tasks/{task_id}/result`，原始结果
和 Artifact 内容必须继续使用带 API Key 的下载接口。

## 游标分页、过滤和排序

所有返回 `page` 的列表接口都使用不透明游标。调用方不得解析或修改游标，
也不能把游标复用于不同的排序字段或排序方向：

```bash
curl -G http://localhost:8080/api/v1/tasks/task_xxx/artifacts \
  -H "Authorization: Bearer $PARSER_SERVE_API_KEY" \
  --data-urlencode "types=result_text" \
  --data-urlencode "types=result_markdown" \
  --data-urlencode "sort_by=created_at" \
  --data-urlencode "sort_direction=asc" \
  --data-urlencode "limit=50"
```

当响应的 `page.has_more` 为 `true` 时，把 `page.next_cursor` 原样放入下一次
请求的 `cursor` 参数，并保持其他过滤与排序参数不变。所有列表均提供稳定
默认顺序；Task、Stage、Artifact、Backend、Pipeline、Worker、API Key、
Event、Callback Delivery 和 Callback Attempt 还接受强类型 `sort_by` 与
`sort_direction`。

Stage 列表可按状态、Backend 和 Worker 过滤，并按 `position` 或
`created_at` 排序。Artifact 列表可按类型和 MIME Type 过滤，并按
`created_at`、`filename` 或 `size_bytes` 排序。

Event 默认按发生时间升序，以保持 SSE 与 JSON 查询的消费顺序一致；显式倒序
仅用于历史查询。Callback Attempt 默认按投递序号倒序，也可按开始时间或耗时
排序，并通过 `delivered` 过滤结果。

## 管理接口

普通 API Key 可以直接访问 `/api/v1/management/*`，用于外部系统管理
Worker、Backend、Pipeline、Callback、动态设置和保留策略。例如：

```bash
curl http://localhost:8080/api/v1/management/workers?limit=100 \
  -H "Authorization: Bearer $PARSER_SERVE_API_KEY"
```

修改接口使用与 OpenAPI 一致的严格请求模型；未知字段、错误枚举和类型不匹配
均返回 `422`。错误响应统一包含 `error.code`、`message`、`retryable`、
`field_violations` 和 `context`。集成方应根据 `retryable` 和 HTTP 状态决定
是否重试，不应通过匹配错误文本做控制流判断。错误码语义、HTTP 映射与兼容
规则见[错误响应与稳定错误码](error-codes.md)。

完整机器可读契约由 `/openapi.json` 提供；仓库中的 `web/openapi.json` 是
用于 Web UI 类型生成和 CI 契约快照的版本。

## Schema 元数据

所有请求、响应和事件对象继承严格 `StrictSchema`：未知字段会被拒绝，枚举、
字符串格式、数值上下限、数组长度和联合类型约束会进入 OpenAPI。组件 Schema
的每个属性以及所有 Path、Query 和 Header 参数都有非空描述；核心资源 ID、
MIME、Schema 版本、时间、哈希和百分比字段还提供合法示例。

公共字段说明由 `schema` 层统一生成，路由参数说明由 OpenAPI 注解层补齐，
避免新增接口时漏写文档。契约测试会拒绝缺少属性或参数描述的 OpenAPI，并
校验提交到 `web/openapi.json` 的快照与运行中应用完全一致。

示例仅用于说明格式，不能作为固定值或长度推断依据；调用方必须以 `pattern`、
`minimum`、`maximum`、`minLength`、`maxLength`、`enum` 和 `required`
等机器约束为准。
