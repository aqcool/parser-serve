# Parser Serve 总体架构规划

## 1. 文档状态

- 状态：规划中
- 适用项目：Parser Serve
- 最后更新：2026-07-24
- 任务清单：[TODO.md](../TODO.md)
- 依赖与镜像说明：[dependency-profiles.md](dependency-profiles.md)

本文档记录 Parser Serve 已确认的产品范围、架构原则、接口规范和实施方向。实现过程中如需调整关键决策，应先更新本文档，再修改代码。

## 2. 产品定位

Parser Serve 是一个面向异构算力的分布式多模态内容解析平台。系统通过统一接口接收文档、图片、网页、音频和视频，组合不同解析能力，将内容转换为结构化、可检索、可追溯的结果。

系统主要服务于：

- 知识库和 RAG 数据处理
- 文档、图片和扫描件 OCR
- Office、PDF 和网页内容抽取
- 音频转写与说话人、时间戳处理
- 视频音轨、字幕、关键帧和画面内容解析
- 企业内部解析能力平台化
- 外部业务系统通过 API、回调或 MCP 集成

## 3. 已确认的范围

### 3.1 内容类型

| 类别 | 典型输入 | 核心能力 |
| --- | --- | --- |
| Office 文档 | DOC、DOCX、PPT、PPTX、XLS、XLSX | DOC/PPT 升级转换、结构和表格提取 |
| 通用文档 | PDF、TXT、Markdown、CSV | 正文、版面、表格、图片和元数据 |
| 图片和照片 | JPEG、PNG、WEBP、TIFF、BMP | OCR、EXIF、图像描述和版面分析 |
| 网页 | URL、HTML | 安全抓取、正文清洗、元数据和动态渲染 |
| 音频 | MP3、WAV、M4A、AAC、FLAC、OGG | FFmpeg 标准化、ASR、时间戳 |
| 视频 | MP4、MOV、MKV、AVI、WEBM | FFmpeg、音轨转写、字幕、关键帧、OCR/VLM |

### 3.2 解析后端

首批计划接入的解析 Backend：

- FFmpeg 和 ffprobe
- MinerU
- PaddleOCR
- PaddleOCR-VL
- HunyuanOCR
- 语音识别 Backend
- 网页正文提取 Backend

LibreOffice 不属于解析 Backend，只作为 `utils` 中的格式转换工具，将 `.doc` 转为 `.docx`、`.ppt` 转为 `.pptx`、`.xls` 转为 `.xlsx`，再交给后续解析流程。

CPU Worker 在下载源文件后运行预处理链。`LegacyOfficePreprocessor` 仅根据
旧格式扩展名调用上述工具，转换结果作为当前 Stage 的有效输入继续交给
真正的文档 Backend；它不注册 Backend Capability，也不能被 Pipeline
直接选作解析 Backend。

### 3.3 硬件平台

系统不能只使用 `use_gpu: bool` 表示硬件，而应明确区分运行时：

- CPU
- NVIDIA CUDA
- 华为昇腾 Ascend
- 寒武纪 MLU
- 海光 DCU
- 摩尔线程 MUSA
- 昆仑芯 XPU

国产硬件按实际拥有的设备和 Backend 兼容性逐个接入，不假设所有模型均能在所有硬件上运行。

### 3.4 对外能力

- 完整类型的 HTTP 业务 API
- 完整类型的开放管理 API
- API Key 鉴权
- 异步任务和实时进度
- 多机 Worker 注册、心跳、租约和任务派发
- 结果回调与可靠重试
- MCP Tools 和 Resources
- Web UI 解析测试、系统管理和数据看板

## 4. 明确不做的能力

当前规划不包含：

- 用户注册和密码登录
- 用户、角色和组织管理
- RBAC
- 多租户数据隔离
- 菜单和字段级权限
- 将全部硬件运行时打入同一个镜像
- 使用单个解析库处理所有内容类型

所有有效的普通 API Key 具有相同的业务和管理 API 访问能力。

## 5. 核心设计原则

### 5.1 控制面与数据面分离

控制面负责接入、任务、路由、调度、回调和管理；数据面负责实际解析。API 进程不直接执行重型解析任务。

### 5.2 Pipeline 与 Backend 分离

- Pipeline 描述内容需要经过哪些解析阶段。
- Backend 描述某个阶段由哪个具体工具、模型或远程服务完成。

一个视频 Pipeline 可以组合 FFmpeg、ASR、OCR 和 VLM，而不是绑定到单个“视频解析器”。

### 5.3 业务路由与算力调度分离

- Pipeline Router 决定“如何解析”。
- Scheduler 决定“在哪台机器、用什么硬件执行”。

### 5.4 协议优先

HTTP、Worker、MCP、回调、SSE 和 Web UI 共用 `parser_serve/schema/` 中的类型定义。Pydantic Schema 是协议的唯一真实来源。

### 5.5 至少一次与幂等

多机任务采用至少执行一次语义。任务、Stage、结果写入和回调接收方都必须支持幂等，不能依赖严格的 exactly-once。

### 5.6 硬件镜像隔离

CPU、CUDA 和各国产硬件使用独立镜像，避免驱动、推理框架和动态链接库冲突。

## 6. 总体架构

```text
                         调用入口
       ┌────────────────────┼────────────────────┐
       │                    │                    │
       ▼                    ▼                    ▼
    Web UI              HTTP API            MCP Client
       │                    │                    │
       └────────────────────┼────────────────────┘
                            │ API Key
                            ▼
┌─────────────────────────────────────────────────────────┐
│                       控制面                             │
│                                                         │
│ API Server              Task Service                    │
│ MCP Server              Pipeline Router                 │
│ Scheduler               Worker Registry                 │
│ Callback Dispatcher     Dashboard Service               │
└───────────────────────────┬─────────────────────────────┘
                            │
          PostgreSQL + Redis Streams + S3/MinIO
                            │
        ┌───────────────────┼────────────────────┐
        │                   │                    │
        ▼                   ▼                    ▼
   CPU Worker          CUDA Worker        国产硬件 Worker
   LibreOffice         NVIDIA GPU         Ascend / MLU / DCU
   FFmpeg              OCR/VLM/ASR        MUSA / XPU
   Web/Text            MinerU             专用模型与运行时
```

### 6.1 控制面

控制面包含：

- API Key 验证
- Public API 和 Management API
- MCP Server
- 文件和对象存储访问
- Task 与 Stage 状态机
- Pipeline 展开
- Worker 注册和健康管理
- 算力调度和租约管理
- 回调投递和重试
- Dashboard 聚合查询
- API 文档和 SDK Schema

控制面不安装 CUDA、CANN、MLU 等硬件推理运行时。

### 6.2 数据面

数据面由分布在不同机器上的 Worker 组成。Worker 负责：

- 向控制面注册
- 上报硬件和 Backend 能力
- 定期发送心跳和资源状态
- 主动领取兼容任务
- 续租长时间任务
- 执行 Backend
- 上报进度、结果和错误
- 优雅下线和停止领取任务

内置 CPU Worker Agent 已实现注册、心跳、主动拉取、租约续期、并发执行、
源文件下载、幂等 Artifact 上传和 Stage 完成回报。第一批内置执行器为：

- `builtin_text@1.0`：UTF-8 文本与 Markdown 结构化解析
- `builtin_pdf@1.0`：PDF 分页文本和文档元数据
- `builtin_office@1.0`：DOCX 段落/表格、PPTX 幻灯片及 XLSX 工作表/单元格
- `builtin_image@1.0`：图片尺寸、格式、帧数和 EXIF
- `builtin_web@1.0`：静态 HTML 标题、正文和链接
- `builtin_ffmpeg@1.0`：ffprobe 元数据和 FFmpeg 音轨标准化

系统工具 Backend 只在启动探测成功时上报；工具可用性同时写入 Worker
标签。后续 PaddleOCR、PaddleOCR-VL、HunyuanOCR、MinerU 和 ASR 均按相同
Backend 接口接入。

`builtin_office` 使用有界 ZIP/XML 读取，限制成员数量、解压后总字节数、单个
XML 大小和异常压缩比，并拒绝路径穿越、加密成员、DTD 与实体声明。旧
`.doc/.ppt/.xls` 仍由 Worker 的 LibreOffice 预处理器升级后交给同一个
Office Backend；LibreOffice 本身不注册为 Backend。

## 7. 接口边界

| 路径 | 用途 | 鉴权 |
| --- | --- | --- |
| `/api/v1/*` | 对外业务解析 API | 普通 API Key |
| `/api/v1/management/*` | 对外开放管理 API | 普通 API Key |
| `/api/v1/events/*` | 对外 SSE 事件流 | 普通 API Key |
| `/mcp` | MCP 接口 | 普通 API Key |
| `/internal/v1/*` | Worker 内部协议 | Worker API Key 和内部网络 |
| `/health` | 进程存活检查 | 可不鉴权，不返回敏感信息 |
| `/ready` | 依赖就绪检查 | 按部署环境限制访问 |

Web UI 不拥有专用接口，也不直接访问数据库或 Worker。Web UI 能完成的操作必须全部可以通过开放管理 API 完成。

## 8. Schema 与类型规范

所有接口入参和出参必须使用完整、可生成 JSON Schema 的 Pydantic 类型。

### 8.1 Schema 目录

```text
parser_serve/schema/
├── __init__.py
├── base.py
├── common.py
├── error.py
├── authentication.py
├── source.py
├── task.py
├── stage.py
├── result.py
├── artifact.py
├── worker.py
├── hardware.py
├── backend.py
├── pipeline.py
├── callback.py
├── event.py
├── dashboard.py
├── management.py
└── mcp.py
```

### 8.2 类型规则

- 请求模型默认 `extra="forbid"`。
- 不在协议边界使用裸 `dict`、`list[dict]`、`Any` 或 `object`。
- 可扩展元数据使用明确的递归 `JsonValue`。
- 固定值使用 `StrEnum`。
- 不同输入来源和内容 Block 使用带 discriminator 的联合类型。
- ID 使用带格式约束的字符串类型。
- 时间使用带时区的 UTC ISO 8601。
- 大小使用 `_bytes`，时间长度明确使用 `_ms` 或 `_seconds`。
- 数据库 ORM、领域模型和 API Schema 相互分离。
- 所有 FastAPI 路由声明 `response_model` 和稳定的 `operation_id`。

### 8.3 统一响应

成功响应：

```json
{
  "request_id": "req_01abc",
  "data": {}
}
```

列表响应：

```json
{
  "request_id": "req_01abc",
  "items": [],
  "page": {
    "next_cursor": null,
    "has_more": false
  }
}
```

错误响应：

```json
{
  "request_id": "req_01abc",
  "error": {
    "code": "WORKER_NOT_AVAILABLE",
    "message": "No compatible worker is currently available",
    "retryable": true,
    "field_violations": []
  }
}
```

### 8.4 OpenAPI 和客户端

```text
Pydantic Schema
       ↓
FastAPI OpenAPI
       ├── Python SDK
       ├── TypeScript SDK
       ├── MCP inputSchema/outputSchema
       └── Web UI API Client
```

Web UI 不手写请求和响应类型。Python SDK 直接复用 Pydantic Schema，并由
OpenAPI 生成稳定 operationId 到 HTTP 方法、路径的映射；同步和异步 Client
共享认证、参数编码、上传、流式下载及类型化错误语义。

本地模型 Backend 可实现显式 `load/unload` 生命周期。Worker 在注册前事务式
预加载指定模型，失败时逆序回滚，Drain 完成后逆序卸载。控制面为每个 Stage
租约绑定具体 `device_id`；多设备 Worker 按活动租约数、实时利用率、显存压力
和稳定设备 ID 排序，Backend 从租约上下文绑定实际执行设备。

OpenTelemetry 作为可选 Profile 使用 OTLP/HTTP 导出。FastAPI 与 HTTPX 负责
HTTP 边界自动传播；Task 创建时持久化严格 W3C Trace Context，Stage 租约和
Remote Backend 协议继续携带，Worker 执行与 Callback 投递从持久化父上下文
创建 Span，从而跨越 API 请求生命周期、数据库队列、机器和重试。

## 9. API 规范

### 9.1 业务解析 API

```text
POST /api/v1/files
GET  /api/v1/files/{file_id}
GET  /api/v1/files/{file_id}/content
POST /api/v1/tasks
GET  /api/v1/tasks
GET  /api/v1/tasks/{task_id}
GET  /api/v1/tasks/{task_id}/stages
GET  /api/v1/tasks/{task_id}/stages/{stage_id}
GET  /api/v1/tasks/{task_id}/result
GET  /api/v1/tasks/{task_id}/result/content
GET  /api/v1/tasks/{task_id}/artifacts
GET  /api/v1/tasks/{task_id}/artifacts/{artifact_id}/content
POST /api/v1/tasks/{task_id}/cancel
POST /api/v1/tasks/{task_id}/retry
```

结构化结果接口只从该 Task 已登记的主结果 Artifact 读取数据，并重新执行
`ParseResult` Schema 校验和 `task_id` 归属校验。控制面不根据 Worker 返回的
任意 URI 直接访问网络或文件系统。JSON 查询有独立字节上限；大结果和原始
格式通过流式内容接口下载。

### 9.2 开放管理 API

管理 API 通过普通 API Key 对外开放，方便其他平台集成。

```text
GET   /api/v1/management/tasks
GET   /api/v1/management/workers
PATCH /api/v1/management/workers/{worker_id}
GET   /api/v1/management/backends
POST  /api/v1/management/backends
GET   /api/v1/management/backends/{backend_id}
PATCH /api/v1/management/backends/{backend_id}
GET   /api/v1/management/pipelines
POST  /api/v1/management/pipelines
GET   /api/v1/management/pipelines/{pipeline_id}/versions/{version}
POST  /api/v1/management/pipelines/{pipeline_id}/versions/{version}/validate
POST  /api/v1/management/pipelines/{pipeline_id}/versions/{version}/test
POST  /api/v1/management/pipelines/{pipeline_id}/versions/{version}/publish
POST  /api/v1/management/tasks/{task_id}/route
GET   /api/v1/management/callbacks
GET   /api/v1/management/callbacks/{delivery_id}
GET   /api/v1/management/callbacks/{delivery_id}/attempts
POST  /api/v1/management/callbacks/{delivery_id}/retry
GET   /api/v1/management/dashboard/summary
GET   /api/v1/management/settings
PATCH /api/v1/management/settings
GET   /api/v1/management/api-keys
POST  /api/v1/management/api-keys
GET   /api/v1/management/api-keys/{api_key_id}
PATCH /api/v1/management/api-keys/{api_key_id}
POST  /api/v1/management/api-keys/{api_key_id}/rotate
DELETE /api/v1/management/api-keys/{api_key_id}
```

Dashboard Summary 默认聚合最近 24 小时，支持 `start_time`、`end_time`、
`interval`、`pipeline_id`、`backend_id`、`worker_id`、`runtime` 和
`media_category`。响应使用 `DashboardData`，包含任务状态与成功率、等待和
执行延迟分位数、Worker 并发、Backend 调用/失败/超时/fallback、Runtime
设备利用率、回调投递、Storage 用量及任务时间序列。单次查询最多生成
10,000 个时间点，避免管理查询造成无界内存占用。

### 9.3 通用约定

- `Authorization: Bearer parser_xxx` 为默认鉴权方式。
- 写操作支持 `Idempotency-Key`。
- 请求和响应携带 `X-Request-ID`。
- 列表接口使用游标分页。
- 过滤、排序和时间范围参数保持一致。
- 错误返回稳定的机器可识别错误码。
- 对外 API 使用 `/api/v1` 版本。
- 解析结果单独携带 `schema_version`。

## 10. API Key

普通 API Key 可以访问业务 API、管理 API、事件流和 MCP。系统不实现 RBAC。

API Key 仅存储：

- ID
- 名称
- Key 前缀
- Key 哈希
- 是否启用
- 过期时间
- 最后使用时间
- 创建和更新时间

安全要求：

- 完整 Key 仅在创建或轮换时显示一次。
- 日志和页面只展示 Key 前缀。
- 不允许删除或禁用最后一个有效普通 API Key。
- Worker 使用独立的 Worker API Key。
- 数据库 Worker Key 必须绑定具体 `worker_id`，不能代表其他 Worker；环境启动 Worker Key 仅用于首次引导。
- Key 比较使用安全的哈希和恒定时间比较。

部署时可以通过环境变量提供不入库的启动 Key，用于首次创建数据库 Key 和故障恢复。日常集成使用数据库 Key；启动 Key 同样不得写入日志或返回给客户端。列表接口使用基于创建时间和 Key ID 的不透明游标，避免暴露数据库偏移量。

## 11. Pipeline 与 Backend

### 11.1 Pipeline

Pipeline 是带依赖关系的 Stage DAG，描述内容解析过程。例如视频：

```text
                    ┌── 音轨提取 ── ASR ──────────┐
输入 ── ffprobe ────┤                              ├── 时间轴合并
                    └── 关键帧 ── OCR / VLM ──────┘
```

Pipeline 必须版本化。已创建任务绑定具体 Pipeline 版本，后续配置修改不能改变历史任务定义。

任务提交后可以短暂处于尚未路由的 `pending` 状态：此时保存强类型原始 Source，但规范化 SourceMetadata 和 Pipeline 版本可以暂时为空。Pipeline Router 完成识别后必须原子绑定具体 `pipeline_id + pipeline_version` 并生成 Stage DAG；任务进入 `leased`、`running`、`succeeded` 或 `failed` 前必须已经绑定版本。任务在路由前被取消时可以没有 Pipeline。

Pipeline 发布前需要校验：

- Stage ID 唯一
- 所有依赖存在
- DAG 不存在循环
- Backend 存在并已启用
- Backend 支持目标媒体类型
- 至少存在一种可执行硬件运行时

同一 Pipeline ID 每次创建产生递增版本。发布一个版本时，同 ID 的其他已发布
版本转为 `disabled`；重新发布历史版本即为回滚。普通任务的 Router 只使用
`published` Pipeline 和 `enabled` Backend，并按 `routing_priority`、
Pipeline 版本、Stage 的 preferred/fallback 顺序及任务硬件约束进行确定性
选择。

Pipeline 管理测试接口是唯一允许执行 `draft` 版本的入口。它先校验完整
Backend 目录和 Source 媒体/MIME 兼容性，再原子创建标准 Task 与 Stage；
后续租约、执行、Artifact、事件和结果协议与普通任务完全一致。校验或路由
失败时事务回滚，不留下 Pending Task；测试不会隐式发布或修改 Pipeline。

### 11.2 Backend

Backend 描述具体解析实现和运行能力，包括：

- 名称和版本
- 支持的媒体类型
- 支持的硬件运行时
- 最低设备内存
- 默认超时
- 最大并发
- 重试策略
- 健康状态

同一逻辑能力可以存在多个实现：

```text
PaddleOCR
├── CPU Backend
├── CUDA Backend
├── Ascend Backend
└── MLU Backend
```

不支持某硬件的 Backend 不得注册该运行时。

### 11.3 远程模型服务协议

独立部署的 MinerU、PaddleOCR、PaddleOCR-VL、HunyuanOCR、ASR 和 VLM
通过 Worker 内的 `RemoteHttpBackend` 接入。协议使用 multipart 流式上传
源文件，并用 Pydantic Schema 约束请求、成功响应、失败响应和辅助 Artifact。
Worker 校验 Task、Source、响应类型、大小和 Artifact 所有权，且不跟随
重定向。完整协议见 [远程 Backend 接入协议](remote-backends.md)。

远程调用仍被视为 Worker 执行：控制面负责选中逻辑 Backend 和 Worker，
Worker 负责模型服务认证与调用。这样模型服务密钥不进入控制面，同时租约、
心跳、重试、回调和结果存储不产生第二套实现。

Router 创建 Stage 时必须固化：

- Pipeline 中的显示顺序和依赖 Stage 名称
- 是否可选、执行超时和最大尝试次数
- 首选 Backend ID/版本及有序候选 Backend ID
- 任务和 Stage 约束交集得到的允许运行时
- Stage 参数

这些数据属于任务创建时的执行快照，后续修改 Backend 或 Pipeline 配置不得改变已路由任务。

Task 创建会在保存点内立即尝试路由。若整个 Stage DAG 无法一次性解析，
保存点回滚，任务以零 Stage 的 Pending 状态提交，避免残留部分执行计划。
控制面的后台 `TaskRoutingService` 按批次重试这类任务；Pipeline 或 Backend
稍后可用后会自动生成不可变 Stage 快照。多控制面副本依靠任务行锁和幂等
Stage 约束协调。

## 12. 多机任务调度

### 12.1 两层调度

1. Pipeline Router 根据输入类型和请求特性生成 Stage DAG。
2. Scheduler 根据 Backend、运行时、设备内存、标签、负载和数据位置选择 Worker。

### 12.2 Worker 主动拉取

Worker 采用注册、心跳、拉取和租约模式，不要求控制面直接访问每台 Worker。

```text
pending → leased → running → succeeded
                           ├→ failed
                           └→ cancelled
```

租约到期且未续租时，任务重新进入待调度状态。

内部 Worker 协议包括：

```text
POST /internal/v1/workers/register
POST /internal/v1/workers/heartbeat
POST /internal/v1/workers/lease
POST /internal/v1/workers/stages/{stage_id}/start
POST /internal/v1/workers/stages/{stage_id}/renew
POST /internal/v1/workers/stages/{stage_id}/progress
POST /internal/v1/workers/stages/{stage_id}/complete
GET  /internal/v1/workers/{worker_id}/files/{file_id}/content
POST /internal/v1/workers/{worker_id}/stages/{stage_id}/artifacts
```

租约完整令牌只返回给获租 Worker，数据库仅保存 SHA-256 摘要。所有启动、续租、进度、Artifact 上传和完成操作同时校验 Worker ID、令牌、状态和过期时间。Worker 只能读取当前活动租约所引用的上传文件。数据库事务、行锁和 PostgreSQL `SKIP LOCKED` 保证并发正确性；Redis Streams 已接入为跨控制面可用性通知，Worker 在第一次数据库租约查询前取得 Stream 游标，空结果时阻塞等待新消息，再次查询数据库。Redis 消息可以重复或丢失，数据库始终是任务状态、租约所有权及幂等结果的最终事实来源。

Task 和 Stage 使用显式状态转换表。成功任务和成功或跳过的 Stage 是终态；失败或取消任务可以手动回到 `pending`，租约过期可以从 `leased` 回到 `pending`。创建、取消和重试必须与状态事件在同一数据库事务中提交。

### 12.3 调度因素

- Backend 是否可用
- 硬件运行时是否兼容
- 空闲设备内存
- Worker 并发和队列长度
- Worker 调度权重
- 机器和区域标签
- 输入文件的数据位置
- Backend 健康状态
- 请求的 `auto`、`prefer` 或 `require` 策略

当前实现对 Pull 请求进行兼容节点准入排序。综合分数由 Worker
`scheduling_weight`、数据库权威活动租约占比、心跳 CPU/设备利用率、设备
内存压力和上报任务数计算；已满并发节点不参与候选。相同分数按活动租约数
和 `worker_id` 稳定决策。这样保留 Worker 主动拉取和数据库权威租约模型，
同时避免异构集群长期由轮询最快的节点独占任务。

`prefer` 策略保留请求中的 Runtime 顺序，并在动态负载评分之前比较 Runtime
层级。例如 `["cuda", "cpu"]` 会在 CUDA Worker 可用时优先 CUDA；CUDA
离线、能力不匹配、显存不足或并发已满时，CPU Worker 自动获得租约。

### 12.4 Ray Serve 定位

Ray Serve 是可选的 Worker Executor，可用于某个集群内部的模型常驻、GPU
Replica、背压和模型组合，但不作为全局异构多机调度的唯一核心。仓库提供
Remote Backend 1.0 Ray Serve Ingress；它执行请求/响应 Schema、文件大小与
SHA-256、超时、认证和结果归属校验。Parser Serve 保留全局租约，Ray Serve
只负责选定模型集群内部的 Replica 与资源。

## 13. 典型解析流程

### 13.1 Office

```text
DOC ── LibreOffice 工具 ── DOCX ── 文档解析 Backend
PPT ── LibreOffice 工具 ── PPTX ── 演示文稿解析 Backend
XLS ── LibreOffice 工具 ── XLSX ── 工作表解析 Backend
DOCX / PPTX / XLSX ─────────────── 对应解析 Backend
```

LibreOffice 不负责内容解析，也不作为 Office 到 PDF 的默认转换链路。

### 13.2 图片和照片

```text
图片
├── 格式、尺寸和方向
├── EXIF
├── 旋转、缩放和去噪
├── OCR
└── 可选 VLM 描述
```

### 13.3 音频

```text
音频
├── ffprobe 元数据
├── FFmpeg 标准化
├── 语音活动检测
├── ASR
└── 时间戳和可选说话人信息
```

### 13.4 视频

视频拆分为可以跨 Worker 调度的 Stage：

- ffprobe
- 音轨提取
- ASR
- 字幕提取
- 关键帧或镜头提取
- OCR/VLM
- 时间轴合并

### 13.5 网页

```text
URL
├── SSRF 检查
├── 静态 HTML 下载和正文提取
└── 必要时使用浏览器渲染
```

静态抓取和动态浏览器渲染必须是不同 Backend。

## 14. 统一解析结果

结果以带 discriminator 的 `Block` 联合类型为核心：

- TextBlock
- HeadingBlock
- TableBlock
- ImageBlock
- TranscriptBlock
- KeyframeBlock
- LinkBlock

定位信息按类型保留：

- 文档页码和坐标
- 工作表和单元格范围
- 幻灯片编号
- 网页来源 URL
- 音视频开始和结束时间
- 图片和关键帧 Artifact ID

大型原始文件和 Artifact 不直接存入数据库。

## 15. 回调

任务提交时可以配置回调 URL、事件类型和签名 Secret。

事件包括：

- `task.created`
- `task.running`
- `task.progress`
- `task.succeeded`
- `task.failed`
- `task.cancelled`

回调要求：

- HMAC 签名
- 事件 ID 和时间戳
- 投递幂等
- 超时
- 指数退避
- 最大重试次数
- 投递历史
- 手动重新投递
- SSRF 防护

回调失败不改变已经成功的解析任务状态。任务状态和回调投递状态分别记录。

当前实现以数据库 Outbox 方式从事务内事件物化投递记录，后台 Dispatcher
通过短期 claim 投递，失败后指数退避，到达最大尝试次数后进入 `failed`
终态。每次 HTTP 尝试作为不可变 `callback_attempts` 记录保存响应状态、
摘要、结构化错误、耗时和起止时间；`sequence` 在 Delivery 全生命周期内
单调递增，`attempt_number` 表示当前自动重试轮次。人工重发只重置轮次，
不删除旧历史；过期 claim 的迟到结果会被审计，但不会覆盖较新 claim 的状态。
普通 API Key 可以查询、过滤、分页读取尝试历史、测试和人工重发。请求使用
`X-Parser-Event-ID`、`X-Parser-Timestamp` 和可选
`X-Parser-Signature`；签名算法为
`HMAC-SHA256(secret, timestamp + "." + raw_body)`。

应用层拒绝 localhost、IP 字面量或 DNS 解析结果中的非公网地址，且不跟随
HTTP 重定向。由于“校验时解析”和“连接时解析”之间仍可能发生 DNS
重绑定，生产环境必须再使用出口代理、网络策略或防火墙限制控制面可访问的
目标网段。回调 Secret 后续还需增加数据库静态加密；日志和管理响应不得返回
Secret。

## 16. MCP

MCP 与 HTTP API 复用相同的 Schema 和 Service 层。

首批 Tools：

- `parser_submit`
- `parser_get_task`
- `parser_get_result`
- `parser_cancel_task`
- `parser_list_capabilities`
- `parser_list_pipelines`
- `parser_list_backends`

首批 Resources：

- `parser://tasks/{task_id}`
- `parser://tasks/{task_id}/result`
- `parser://capabilities`
- `parser://pipelines`
- `parser://backends`

大型文件不直接通过 MCP JSON 参数传递。调用方先通过上传 API 获得 `file_id`，或提交受控的对象存储 URI。

当前实现使用无状态 Streamable HTTP，挂载在 `/mcp`。Tools 与 Resources
直接复用 `schema`、SQLAlchemy Repository 和 Storage，不维护第二套任务
模型。普通启动 API Key 和数据库普通 API Key 均可作为 Bearer Token；
同时兼容 `X-API-Key`，不接受 Worker Key。传输层启用 Host/Origin
allowlist 和 DNS rebinding 防护，反向代理部署必须显式配置对外域名。

## 17. Web UI

### 17.1 技术栈

```text
Vue 3
TypeScript
Vite
shadcn-vue
Tailwind CSS
Vue Router
Pinia
TanStack Query
ECharts
```

可按需要增加 Vue Flow 展示任务 DAG。

### 17.2 产品范围

Web UI 只提供：

1. 解析测试
2. 系统管理
3. 数据看板

不提供用户、角色和租户管理。

### 17.3 页面

```text
解析测试
任务管理
Worker 管理
Pipeline 管理
Backend 管理
回调记录
API Key
系统设置
数据看板
```

解析测试页支持：

- 文件、URL、对象存储和文本输入
- Pipeline、Backend 和硬件偏好
- OCR、表格、VLM、ASR、关键帧等特性开关
- 实时 Stage 进度
- JSON、文本、Markdown、表格和时间轴预览
- Artifact 下载
- 生成 cURL 和复制 API 请求

### 17.4 API Key 连接

Web UI 首次访问时输入 API 地址和 API Key。默认只保存在当前浏览器会话，不把 API Key 放入 URL。

### 17.5 类型生成

Web UI 的 TypeScript Schema 和 API Client 从 OpenAPI 自动生成，禁止重复手写后端接口类型。

当前 `web/` 已建立 Vue 3、TypeScript、Vite、Tailwind CSS 4 和
shadcn-vue（Reka UI）工程，包含会话级 API Key 连接、总览、文本/文件解析
测试、任务查询、任务详情、Worker/Drain 及各管理页面。任务详情使用可携带
`Authorization` 和 `Last-Event-ID` 的流式 Fetch 消费 SSE，断线自动续传，
并保留定时查询作为兜底。结构化结果按判别联合类型安全渲染，不使用
`v-html`；Artifact 内容先通过鉴权 Fetch 获取，再以临时 Object URL 预览或
下载，API Key 不进入资源 URL。控制面使用精确 CORS Origin allowlist 支持
独立开发端口；生产同源部署无需放宽该列表。OpenAPI 导出、仓库内置
TypeScript SDK 生成器、65 个 operationId 的运行时 Client 和防漂移测试已经
接通；页面业务 Client 通过生成 operation 调用后端，二进制媒体预览保留专用
流式封装。Python SDK 同样从该 OpenAPI 快照生成全部 operationId 路由，并
复用服务端 Pydantic Schema 提供同步、异步 Client 和统一类型化错误。

## 18. 存储与中间件

第一版推荐：

| 用途 | 组件 |
| --- | --- |
| 任务、配置和投递记录 | PostgreSQL |
| Stage 可用性通知和长轮询唤醒 | Redis Streams |
| 任务状态、租约和幂等结果 | PostgreSQL |
| 原始文件、结果和中间产物 | S3 或 MinIO |
| 指标 | Prometheus |
| 日志 | 标准结构化日志，后续接入 Loki |
| 链路追踪 | OpenTelemetry |

Redis Streams 后续可根据规模替换为 NATS JetStream 或 Kafka，但第一版不同时引入多个消息系统。

数据库模型使用 SQLAlchemy 2.x，版本迁移使用 Alembic。历史迁移必须显式描述表、约束和索引，不能在迁移脚本中调用当前版本的 `Base.metadata.create_all()`，避免模型演进改变历史迁移结果。生产环境由独立发布步骤先执行 `alembic upgrade head`，控制面进程本身不在启动时自动建表或升级。

Storage 通过统一异步流式接口隔离实现。开发和单机测试可使用本地文件
存储；写入必须使用同目录临时文件加原子替换，同时执行大小限制和
SHA-256 计算，内部对象 Key 不使用客户端文件名且必须阻止路径穿越。生产
多机部署使用 S3/MinIO，数据库只保存文件元数据、对象 Key 和 URI。

上传文件通过不可猜测的 `file_id` 被 Task 引用。普通 API Key 可以查询和
下载上传内容；Worker API Key 只能通过
`/internal/v1/workers/{worker_id}/files/{file_id}/content` 下载，并且控制面
必须确认该 Worker 当前持有引用此文件的活动 Stage 租约。MIME、扩展名和
媒体类别仅作为接入阶段元数据，实际 Worker 仍需校验内容签名。

URL Source 在 Task 创建时规范化为 Web 元数据，实际抓取只发生在持有租约的
Worker。Fetcher 仅允许 HTTP(S) 公网地址，拒绝凭证、localhost、非公网或
混合 DNS 结果、HTTPS 到 HTTP 降级、非网页 MIME、超时和超限响应，并逐跳
校验重定向。静态网页 Backend 使用原始 URL 还原相对链接。应用层 DNS
校验无法独立消除解析与连接之间的重绑定窗口，生产 Worker 必须配合出口代理
或网络策略禁止访问内网和云元数据地址。

Object Storage Source 第一版限定为 `s3://bucket/key`，支持可选 VersionId。
Task 只保存 URI 和推导后的媒体元数据，持有租约的 Worker 使用 boto3 标准
凭证链流式下载。每个 Worker 必须配置 Bucket allowlist，默认空列表表示禁止
对象读取；下载同时校验声明长度、实际长度和最大字节数。S3/MinIO 客户端以
`object-storage` 可选依赖 Profile 与任一硬件 Worker 组合。

## 19. 实时事件

第一版使用 SSE：

```text
GET /api/v1/events/stream
GET /api/v1/tasks/{task_id}/events/stream
```

同时提供同过滤语义的持久化 JSON 查询：

```text
GET /api/v1/events
GET /api/v1/tasks/{task_id}/events
```

事件至少包含：

- `task.status_changed`
- `task.progress_updated`
- `worker.registered`
- `worker.online`
- `worker.offline`
- `worker.unhealthy`
- `callback.failed`

Web UI 使用支持自定义 Authorization Header 的流式 Fetch，不通过查询参数传递 API Key。
客户端可以使用 `Last-Event-ID` Header 续传；若游标不存在或已过期，服务端
返回 404，由客户端重新获取当前任务快照。事件默认保留 7 天；回调源事件在
物化投递前不清理，因此不会因保留周期丢失回调工作。慢消费者限制仍属于
后续生产化工作。Redis Streams 当前用于
Stage 可用性长轮询唤醒，不替代可恢复的数据库事件历史。

所有事件生产者通过 `TransactionalEventPublisher` 发布严格 `EventPayload`，
数据库实现与业务 Session 共享事务。JSON 查询和 SSE 通过 `EventConsumer`
读取同一 Outbox；Callback 使用带行锁和已处理标记的专用消费者语义。后续
外部 Broker 只能作为提交后的 Relay，不参与业务双写，详细边界见
`docs/events.md`。

## 20. 镜像和部署

### 20.1 镜像

```text
parser-control-plane
parser-web
parser-worker-cpu
parser-worker-cuda
parser-worker-ascend
parser-worker-mlu
parser-worker-dcu
parser-worker-musa
parser-worker-xpu
```

`parser-worker-cpu` 包含 LibreOffice、FFmpeg、网页和基础文档能力。其他 Worker 镜像基于各厂商运行时构建，不能继承 CUDA Worker 镜像。

上述独立 Dockerfile 已落库，详见 [容器镜像说明](container-images.md)。
厂商镜像允许在硬件联调阶段以零 Backend 能力注册，仅用于展示设备状态，
不会获得解析任务；真实设备探测和模型 Backend 仍按硬件平台逐项实现。

### 20.2 Python 依赖 Profile

`pyproject.toml` 只把 Pydantic 和 Settings 保留为所有进程共享的核心依赖。镜像根据职责选择 optional dependency：

| 镜像或用途 | uv 参数 |
| --- | --- |
| 控制面 | `--extra control-plane` |
| 仅 HTTP 接入 | `--extra http-api` |
| 仅 MCP 接入 | `--extra mcp` |
| CPU Worker | `--extra worker-cpu` |
| NVIDIA Worker | `--extra worker-cuda` |
| Ascend Worker | `--extra worker-ascend` |
| MLU Worker | `--extra worker-mlu` |
| DCU Worker | `--extra worker-dcu` |
| MUSA Worker | `--extra worker-musa` |
| XPU Worker | `--extra worker-xpu` |
| 可选 Ray Serve Executor | 额外增加 `--extra ray-serve` |

生产镜像使用锁文件安装且不包含开发依赖：

```bash
uv sync --frozen --no-dev --extra control-plane
uv sync --frozen --no-dev --extra worker-cpu
uv sync --frozen --no-dev --extra worker-cuda --extra ray-serve
```

厂商 SDK、推理框架和模型 Backend 依赖只允许加入匹配的硬件 Profile。LibreOffice、FFmpeg、驱动和设备运行时属于系统依赖，由对应 Dockerfile 安装。

### 20.3 单机开发

```text
Docker Compose
├── control-plane
├── web
├── worker-cpu
├── PostgreSQL
├── Redis
└── MinIO
```

数据库迁移后通过 `POST /api/v1/management/defaults/initialize` 幂等安装
内置 Backend 和七类默认 Pipeline。初始化不是应用启动时的隐式副作用；
调用方可审计返回的创建、发布、保持 Draft 和缺失 Backend 信息。只有校验
通过的 Pipeline 才发布，因此尚未接入模型服务时不会产生虚假的可用能力。

动态系统设置存储在 `system_settings` 表，通过普通 API Key 访问
`GET/PATCH /api/v1/management/settings`。只允许修改已经真正接入执行路径的
上传限制、结果 JSON 限制和回调尝试次数；数据库值覆盖部署默认值。HTTP、
MCP、回调物化和 Worker Artifact 上传读取同一套有效值，避免“页面保存成功
但运行不生效”。

上传文件、Artifact 和事件由控制面的 Retention Service 定期分批清理。
上传文件和 Artifact 都记录显式 `expires_at`；历史空值按部署级保留周期
回退计算。活跃任务引用的上传文件及其 Artifact 会跳过，存储删除失败时
数据库元数据保留，以便下一轮重试。普通 API Key 可调用
`POST /api/v1/management/maintenance/retention/run` 进行可审计的试运行或
立即清理，详细规则见 `docs/retention.md`。

### 20.4 多机

控制节点部署控制面和基础设施，各计算节点运行匹配本机硬件的 Worker。Worker 通过任务队列和内部 API 与控制面交互。

### 20.5 Kubernetes

每种硬件使用独立 Deployment、RuntimeClass、资源声明和 Node Selector。Parser Scheduler 选择 Worker 能力，Kubernetes 负责把 Worker 放置到正确物理节点。

## 21. 安全

- 文件扩展名、MIME 和内容签名联合校验
- 文件大小、页数、媒体时长和执行时间限制
- Office、PDF、图片和媒体解析进程隔离
- 防范压缩炸弹、路径穿越和恶意宏
- URL 和回调地址执行 SSRF 防护
- 临时目录隔离和自动清理
- 日志不记录原始敏感内容、API Key 或回调 Secret
- Artifact 使用短期签名 URL
- Worker 内部接口使用独立 Key 和网络策略

## 22. 可观测性

### 22.1 日志

结构化日志至少包含：

- request_id
- task_id
- stage_id
- worker_id
- pipeline 和版本
- backend 和版本
- runtime
- duration_ms
- error_code

### 22.2 指标

- 任务数量、成功率和错误率
- 排队、租约和执行耗时
- Pipeline 和 Backend P50/P95/P99
- Worker 在线状态和心跳延迟
- CPU、内存、设备利用率和设备内存
- 回调成功率和重试次数
- 存储用量

### 22.3 追踪

HTTP 请求、Task、Stage、Worker 执行和回调投递通过 OpenTelemetry Trace 关联。

## 23. 代码目录目标

```text
parser-serve/
├── parser_serve/
│   ├── schema/
│   ├── api/
│   ├── mcp/
│   ├── domain/
│   ├── persistence/
│   ├── control/
│   ├── pipelines/
│   ├── backends/
│   ├── worker/
│   ├── callbacks/
│   ├── dashboard/
│   ├── queue/
│   ├── storage/
│   └── observability/
├── web/
├── deploy/
│   ├── docker/
│   ├── compose/
│   └── kubernetes/
├── tests/
└── pyproject.toml
```

`utils/libreoffice.py` 固定保留为无状态转换工具，不迁移到 Backend。Document Pipeline 只调用其 `.doc → .docx`、`.ppt → .pptx`、`.xls → .xlsx` 能力。

## 24. 实施阶段

### 阶段一：类型和控制面骨架

- 建立完整 Schema
- API Key
- PostgreSQL、Redis Streams 和对象存储接口
- Task、Stage 和 Event 状态模型
- Public API 和 Management API 骨架

### 阶段二：CPU Worker 和分布式任务

- Worker 注册、心跳和能力上报
- 拉取、租约、续租和故障重派
- LibreOffice 旧格式转换工具、FFmpeg、文本和网页 Backend
- 默认文档、图片、音频和视频 Pipeline

### 阶段三：Web UI、回调和 MCP

- shadcn-vue Web UI
- 解析测试、管理和看板
- HMAC 回调和可靠重试
- MCP Tools 和 Resources
- OpenAPI Client 生成

### 阶段四：NVIDIA GPU

- CUDA Worker 镜像
- PaddleOCR、MinerU、ASR 和 VLM
- 模型常驻、设备内存和并发控制
- 可选 Ray Serve Executor

### 阶段五：国产硬件

- 按实际设备依次增加专用 Worker 镜像
- 设备探测和资源指标
- Backend 兼容性声明
- 异构调度、降级和端到端测试

### 阶段六：生产化

- 完整可观测性
- 安全加固
- 容量和故障测试
- Docker Compose 和 Kubernetes 部署
- SDK、运维文档和发布流程

## 25. 验收原则

一个功能只有同时满足以下条件才视为完成：

- 有明确的 Schema
- API、Worker、MCP 或回调协议与 Schema 一致
- 有正常、异常和边界测试
- 有错误码和可观测信息
- 有对应文档
- 不破坏既有 OpenAPI 兼容性
- 适用时可在 Web UI 中测试或管理
