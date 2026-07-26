# 可观测性

## OpenTelemetry Trace

OpenTelemetry 是独立可选依赖，不启用时不会导入 SDK 或改变请求执行。镜像先
组合 `telemetry` Profile，再配置控制面：

```text
PARSER_SERVE_OTEL_ENABLED=true
PARSER_SERVE_OTEL_EXPORTER_ENDPOINT=http://otel-collector:4318/v1/traces
PARSER_SERVE_OTEL_SAMPLE_RATIO=1.0
PARSER_SERVE_OTEL_SERVICE_NAME=parser-serve-control-plane
```

Worker 使用对应的 `PARSER_WORKER_OTEL_*` 变量。Exporter 使用 OTLP/HTTP 和
BatchSpanProcessor；生产建议发送到 OpenTelemetry Collector。采样使用
ParentBased + TraceIdRatioBased，保证父 Trace 未采样时下游不会擅自重新采样。

FastAPI Instrumentation 自动接收 W3C `traceparent`，HTTPX Instrumentation
自动向 Worker 控制请求、远程 Backend 和 Callback 注入上下文。Task 创建时把
当前 `traceparent`/`tracestate` 作为独立 JSON 列持久化；它不参与任务幂等
摘要。Stage 租约携带该上下文，Worker 以它为父创建
`parser.stage.execute`，Callback Dispatcher 以同一 Task 上下文创建
`parser.callback.deliver`。因此 API 请求结束后，即使 Stage 或回调在另一台
机器、稍后重试，仍保持同一个 Trace ID。

主要业务属性包括 `parser.task.id`、`parser.stage.id`、
`parser.worker.id`、`parser.backend.name`、`parser.runtime`、
`parser.device.id`、`parser.callback.delivery.id` 和尝试次数。Span 不记录
API Key、Callback Secret、文件正文或解析内容。任何外部服务 URL 都不得把
密钥放入 Query；认证只使用 Header。

Helm 的 `telemetry.enabled` 默认关闭；开启前必须让控制面与 Worker 镜像包含
`telemetry` Profile，并在 NetworkPolicy `additionalEgress` 中明确放行私有
Collector。官方实现依据
[OTLP Exporter](https://opentelemetry.io/docs/languages/python/exporters/)、
[W3C 上下文传播](https://opentelemetry.io/docs/languages/python/propagation/)、
[FastAPI Instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html)
和
[HTTPX Instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/httpx/httpx.html)。

Parser Serve 当前提供 JSON 结构化日志、Prometheus 指标、类型化管理看板、
可选的 Prometheus Operator 抓取与基础告警规则，以及本节所述的可选
OpenTelemetry Trace。

## 日志

控制面和 Worker 默认向标准错误输出单行 JSON。可配置：

```text
PARSER_SERVE_LOG_LEVEL=INFO
PARSER_SERVE_LOG_FORMAT=json
PARSER_WORKER_LOG_LEVEL=INFO
PARSER_WORKER_LOG_FORMAT=json
```

`PARSER_*_LOG_FORMAT=text` 可用于本地人工调试。控制面使用自己的结构化 HTTP
访问日志，因此容器关闭 Uvicorn 的重复访问日志。

通用字段为：

| 字段 | 含义 |
| --- | --- |
| `timestamp` | UTC ISO 8601 时间 |
| `level`、`logger`、`message` | 日志级别、来源和消息 |
| `request_id` | 接受合法 `X-Request-ID`，否则由控制面生成 |
| `task_id`、`stage_id`、`worker_id` | 路径参数或 Worker 执行上下文中的关联 ID |
| `method`、`path`、`route`、`status_code` | HTTP 访问结果 |
| `duration_ms` | HTTP 请求耗时 |

ContextVar 保证并发请求和并行 Stage 之间不串联上下文。日志不得附带
Authorization、API Key、回调 Secret、远程 Backend Token、原始文档内容或
完整回调响应。

## Prometheus

启用配置：

```text
PARSER_SERVE_METRICS_ENABLED=true
```

端点为 `GET /metrics`，必须使用普通 API Key；Worker API Key 无权抓取：

```bash
curl -H "Authorization: Bearer $PARSER_SERVE_API_KEY" \
  http://localhost:8000/metrics
```

当前指标：

| 指标 | 类型 | 说明 |
| --- | --- | --- |
| `parser_http_requests_total` | Counter | 当前控制面进程的请求数 |
| `parser_http_request_duration_seconds` | Histogram | 当前控制面进程的请求耗时 |
| `parser_task_records` | Gauge | 按状态统计数据库 Task |
| `parser_stage_records` | Gauge | 按状态统计数据库 Stage |
| `parser_worker_records` | Gauge | 按状态统计数据库 Worker |
| `parser_callback_deliveries` | Gauge | 按状态统计回调投递 |
| `parser_callback_attempt_records` | Gauge | 回调尝试历史总数 |
| `parser_backend_stage_attempts` | Gauge | 按 Backend ID 统计 Stage 尝试 |
| `parser_storage_bytes` | Gauge | 上传和 Artifact 元数据中的字节数 |
| `parser_worker_concurrency` | Gauge | Worker 总槽位和已用槽位 |

HTTP 标签中的 `route` 使用 FastAPI 路由模板，不使用实际 Task、Stage 或
Worker ID，防止标签基数无界增长。持久化 Gauge 在每次抓取时直接从数据库
刷新；数据库不可用时返回类型化 `503 dependency_unavailable`，不会输出过期
业务快照。

多副本部署时，每个控制面实例分别暴露自己的 HTTP Counter/Histogram，因此
Prometheus 应对这些指标求和。数据库 Gauge 在每个副本中代表同一全局快照，
查询时应取最大值而不是求和。`/metrics` 不应直接暴露到公网；生产环境应同时
使用 TLS、网络策略和单独的普通 API Key。

任务成功率、延迟分位数、Worker/Backend/硬件、Callback 和 Storage 的带时间
窗口统计由
`GET /api/v1/management/dashboard/summary` 提供，Web UI 和外部系统共用该
类型化接口。

## Kubernetes 抓取与告警

Helm Chart 可以创建 `ServiceMonitor` 和 `PrometheusRule`。二者默认关闭，
因为集群必须先安装 Prometheus Operator CRD，并准备一个只用于监控的普通
API Key Secret：

```bash
kubectl -n parser-serve create secret generic parser-serve-monitoring \
  --from-file=api-key=/secure/monitoring-api-key
```

Secret 的 `api-key` 只包含原始 Key，不包含 `Bearer ` 前缀。

```yaml
monitoring:
  serviceMonitor:
    enabled: true
    labels:
      release: kube-prometheus-stack
    authorization:
      existingSecret: parser-serve-monitoring
      key: api-key
  prometheusRule:
    enabled: true
    labels:
      release: kube-prometheus-stack
    pendingTasksWarning: 100
    retryWaitStagesWarning: 50
    callbackFailuresWarning: 1
    httpServerErrorRatioWarning: 0.05
    workerSaturationRatioWarning: 0.9
```

如果同时启用 Helm NetworkPolicy，必须在
`networkPolicy.controlPlane.additionalIngress` 中允许 Prometheus 所在
Namespace/Pod Selector 访问 `8000/TCP`。不要为抓取方便把 `/metrics` 暴露
到公网。

默认规则包括：

| 告警 | 默认持续时间 | 处理方向 |
| --- | ---: | --- |
| `ParserServeControlPlaneDown` | 5 分钟 | 检查 Deployment、Service、鉴权 Secret 和抓取配置 |
| `ParserServeNoOnlineWorkers` | 5 分钟 | 检查 Worker Key、心跳、硬件探测和网络 |
| `ParserServeHighServerErrorRatio` | 10 分钟 | 按 Route 和 Request ID 检查 5xx 日志 |
| `ParserServePendingTaskBacklog` | 10 分钟 | 检查路由、Worker 能力和容量 |
| `ParserServeRetryWaitStageBacklog` | 10 分钟 | 检查 Backend 错误、租约和依赖 |
| `ParserServeWorkerSaturation` | 15 分钟 | 扩容对应 Runtime Worker 或调整并发 |
| `ParserServeCallbackFailures` | 15 分钟 | 检查接收方、投递历史并决定是否人工重发 |

数据库 Gauge 在每个控制面副本中是同一全局快照，因此告警表达式使用 `max`
聚合；HTTP Counter/Histogram 则跨实例求和。阈值是初始安全值，应根据真实
流量、SLO 和告警噪声调整。部署后应使用测试告警或临时降低阈值，确认规则被
Prometheus 加载并能到达实际通知渠道。
