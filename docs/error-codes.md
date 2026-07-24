# 错误响应与稳定错误码

所有 HTTP JSON 错误都使用 `ErrorResponse`，并返回与响应头
`X-Request-ID` 相同的 `request_id`：

```json
{
  "request_id": "req_01J00000000000000000000000",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request is invalid",
    "retryable": false,
    "field_violations": [
      {"field": "body.source", "reason": "Field required"}
    ],
    "context": {}
  }
}
```

集成方应将 HTTP 状态、`error.code` 和 `error.retryable` 共同作为处理依据：

- `error.code` 是稳定、可编程判断的业务分类。
- `message` 用于诊断，可能随版本或上下文变化，不应参与程序分支。
- `retryable=true` 表示同一操作可以在退避后重试；它不保证重试一定成功。
- `field_violations` 仅描述请求字段问题；`context` 只包含该错误额外公开的结构化信息。
- 未知错误码必须按未知服务端错误处理。客户端不能因为本地枚举较旧而拒绝反序列化整个响应。

## 错误码目录

“常见 HTTP 状态”是默认映射，不排除同一业务分类在不同资源状态下使用表中
列出的其他状态。OpenAPI 中具体操作声明的响应状态始终是该操作的最终契约。

| 错误码 | 常见 HTTP 状态 | 默认可重试 | 含义与调用方处理 |
| --- | --- | --- | --- |
| `VALIDATION_ERROR` | 400、422 | 否 | 请求结构、字段组合或业务前置条件无效；修正请求后再提交。 |
| `AUTHENTICATION_FAILED` | 401、403 | 否 | 缺少、无效或无权用于当前接口的 API Key；不要自动重试同一凭证。 |
| `API_KEY_EXPIRED` | 401 | 否 | 预留：API Key 已过期；当前版本仍统一返回 `AUTHENTICATION_FAILED`，避免暴露凭证状态。 |
| `NOT_FOUND` | 404 | 否 | 请求的资源不存在，或调用方不可见。 |
| `CONFLICT` | 409 | 否 | 当前资源状态、幂等键内容或并发操作发生冲突；应先重新读取资源。 |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | 否 | 输入内容类型不在接口或所选 Pipeline 支持范围内。 |
| `FILE_TOO_LARGE` | 413 | 否 | 上传、下载或远程 Backend 产物超过配置上限。 |
| `TASK_NOT_CANCELLABLE` | 409 | 否 | Task 已处于不能取消的终态或状态。 |
| `WORKER_NOT_AVAILABLE` | 409、503 | 是 | 当前没有兼容且可接单的 Worker；调用方可退避重试。 |
| `BACKEND_NOT_AVAILABLE` | 409、503 | 视上下文 | Backend 未启用、能力不匹配或暂时不可用；以响应中的 `retryable` 为准。 |
| `TIMEOUT` | 408、504 | 是 | Worker、Backend 或外部依赖在期限内未完成。 |
| `RATE_LIMITED` | 429 | 是 | 预留：请求超过限流策略；当前版本尚未启用入口限流。启用后应同时返回 `Retry-After`。 |
| `DEPENDENCY_UNAVAILABLE` | 502、503、504 | 是 | 数据库、对象存储、远程 Backend 等依赖不可用。 |
| `INTERNAL_ERROR` | 500 | 否 | 未分类的服务端错误；携带 `request_id` 联系运维，不要高频重试。 |

## 重试与幂等

只对 `retryable=true` 的响应进行带抖动的指数退避，并设置最大尝试次数。若服务
返回 `Retry-After`，应优先遵守该值。创建 Task、上传 Artifact 和 Stage 完成
等支持幂等的写操作必须复用原有幂等键；不能用一次重试生成一个新键，否则可能
产生重复资源。

认证失败、参数错误、内容不支持、文件超限和确定性的状态冲突不应原样重试。
`500 INTERNAL_ERROR` 默认不可重试，是为了避免在服务端状态不明时放大故障；
调用方只有在确认操作幂等后才可进行有限重试。

## 兼容性

现有错误码的语义不会在兼容版本中重定义。服务端可以新增错误码、补充
`context` 字段，或调整面向人的 `message`。删除或重命名错误码属于协议破坏性
变更。仓库契约测试会校验本目录与 `schema.ErrorCode` 保持同步。
