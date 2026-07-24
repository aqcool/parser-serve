# Parser Serve

Parser Serve 是一个面向文档、图片、网页、音频和视频的分布式多模态解析服务。它通过统一、强类型的任务协议接入不同解析能力，并把文本、版面、表格、OCR、媒体时间轴、元数据和中间产物转换为标准结果。

项目当前处于控制面基础实施阶段，尚不是完整可用的解析产品。已完成的代码和规划中的能力会在下文明确区分。

## 核心设计

- 统一入口：HTTP API、开放管理 API 和 MCP 复用同一套 `schema` 与业务服务。
- 完整类型：请求、响应、事件、回调和 Worker 协议均使用严格 Pydantic Schema，禁止未知字段。
- 异构执行：CPU、NVIDIA CUDA、Ascend、MLU、DCU、MUSA、XPU 使用独立 Worker Profile 和镜像。
- Kubernetes Helm Chart 按 Runtime 分离 Node Selector、设备资源和 Worker Deployment，并包含迁移 Hook 与 Drain 滚动升级流程。
- 分布式调度：Worker 主动拉取任务，通过数据库权威租约、续租、重派、Redis Streams 跨控制面唤醒和幂等写入支持多机执行。
- 可插拔 Backend：PaddleOCR、PaddleOCR-VL、HunyuanOCR、MinerU、ASR、VLM 等实现放入 `parser_serve/backends/`，由能力注册和 Pipeline Router 选择。
- 可靠回调：支持 HMAC 签名、超时、指数退避、逐次尝试审计、失败终止和手动重发。
- 简单鉴权：不引入 RBAC，普通 API Key 可调用业务接口和对外开放的管理接口；Worker 使用独立 API Key。
- 管理界面：Web UI 采用 Vue 3、TypeScript、Vite 和 shadcn-vue，提供解析测试、管理和看板。

## 内容范围

| 类别 | 典型输入 | 目标能力 |
| --- | --- | --- |
| Office | DOC、DOCX、XLS、XLSX、PPT、PPTX | 正文、表格、工作表、幻灯片、版面和元数据 |
| 通用文档 | PDF、TXT、Markdown、CSV | 文本、章节、表格、页码和结构化区块 |
| 图片与照片 | JPG、PNG、WEBP、TIFF、BMP | OCR、尺寸、EXIF、版面和图像描述 |
| 网页 | URL、HTML | 静态或渲染后正文、链接和页面元数据 |
| 音频 | MP3、WAV、M4A、AAC、FLAC、OGG | 语音转写、说话人和时间戳 |
| 视频 | MP4、MOV、AVI、MKV、WEBM | 媒体信息、音轨转写、关键帧和时间轴 |

LibreOffice 仅是无状态格式转换工具，用于 `.doc → .docx`、`.ppt → .pptx` 和 `.xls → .xlsx`，不作为解析 Backend。FFmpeg/ffprobe 用于音视频探测、解码、转码和关键帧提取。

## 当前已实现

- 严格的 Source、Task、Stage、Result、Artifact、Pipeline、Backend、Worker、Callback、Event、Dashboard、API Key 和 MCP Schema。
- FastAPI 应用工厂、健康检查、就绪检查、系统信息、能力查询、统一错误响应和 `X-Request-ID`。
- `Authorization: Bearer` 与 `X-API-Key` 鉴权，支持启动密钥和数据库密钥。
- API Key 创建、查询、过滤、游标分页、更新、启停、轮换和删除管理接口；完整 Key 仅创建或轮换时返回一次。
- SQLAlchemy 异步数据库基础、10 张控制面核心表、API Key 摘要存储与最后有效 Key 保护。
- 流式文件上传、元数据和内容查询，本地存储支持原子写入、大小限制、SHA-256 及路径穿越防护。
- 上传文件 Source 会自动补齐媒体类别和元数据；Worker 仅能下载其活动租约对应的源文件。
- Worker 可在有效 Stage 租约内上传 Artifact；普通 API Key 可列出并下载任务产物。
- Task/Stage 显式状态机，以及文本任务创建、规范化、查询、过滤、游标分页、取消和重试 API。
- Stage 和 Artifact 子资源支持强类型过滤、稳定游标分页以及字段和方向排序。
- 单任务 Stage 列表/详情，以及经过 `ParseResult` Schema 校验的结果查询和原始结果流式下载。
- URL Source 元数据规范化及 Worker 受控抓取，支持静态网页解析、相对链接还原、重定向逐跳校验和下载上限。
- S3/MinIO Object Storage Source，支持 Bucket allowlist、VersionId、流式大小限制和可选 Endpoint。
- 任务提交 `Idempotency-Key`、请求冲突检测和事务内任务状态事件。
- Backend Registry，以及 Backend 创建、过滤、配置、启停和能力查询接口。
- Pipeline 草稿、自动版本、DAG/Backend 能力校验、发布和旧版本回滚。
- Pipeline Draft/Published 指定版本真实测试任务，测试不隐式改变发布状态。
- Pipeline Router 按媒体、硬件要求、优先 Backend 与 fallback 原子生成 Stage DAG。
- 独立且绑定 `worker_id` 的 Worker API Key；普通 Key 与 Worker Key 不能跨接口使用。
- Worker 注册、能力上报、单调心跳、管理、Drain 和离线协调。
- Worker 主动拉取 Stage，支持安全租约令牌、启动、进度、续租、完成、指数退避和租约过期重派。
- 可运行的 CPU Worker Agent，负责注册、心跳、租约续期、并发执行、文件下载、Artifact 上传和结果回报。
- 内置文本/Markdown、PDF、静态 HTML、图片/照片元数据 Backend，以及 ffprobe 媒体探测和 FFmpeg 音轨标准化 Backend。
- 内置 DOCX、PPTX、XLSX Office Open XML Backend，支持段落、表格、幻灯片和工作表定位，并限制压缩包与 XML 资源使用。
- LibreOffice 严格作为 Worker 源文件预处理工具，不注册为解析 Backend。
- 统一远程 Backend 1.0 协议，可配置接入 MinerU、PaddleOCR、
  PaddleOCR-VL、HunyuanOCR、ASR、VLM 和动态网页渲染；包含认证、流式文件
  上传、超时、响应与 Artifact 大小限制、严格结果校验和错误重试映射。
- 上述解析引擎提供严格类型的预设配置，自动生成与默认 Pipeline 一致的名称、
  MIME、媒体类别和当前 Worker Runtime 能力。
- Worker 同时强制执行全局并发和每个 Backend 的 `maximum_concurrency`。
- Task 提交、Worker Artifact 上传和 Stage 完成都支持幂等重放及内容冲突检测。
- 持久化事件查询、全局/单任务 SSE、`Last-Event-ID` 断线续传和 API Key 鉴权。
- 事务型 Database Event Bus，统一 Task、路由、Stage、Worker、Callback 和
  MCP 的类型化事件发布，并为 JSON/SSE 提供游标消费者接口。
- 上传文件、Artifact 和事件保留策略，支持后台分批清理、管理 API
  试运行/执行和 Web 管理；活跃任务及待物化回调事件不会被误删。
- 任务创建、运行、进度、成功、失败和取消回调，以及投递查询、测试和人工重发管理接口。
- 回调采用 HMAC-SHA256 签名、HTTP 超时、指数退避和最大尝试次数，并拒绝解析到非公网地址的目标和 HTTP 重定向。
- `/mcp` 无状态 Streamable HTTP 服务，提供任务提交、查询、结果、取消、能力、Pipeline 和 Backend Tools/Resources。
- 调度会检查 Backend/Runtime、任务硬件策略、Worker 标签、设备可用内存和
  最大并发，并按 Worker 调度权重、权威活动租约、CPU/设备利用率和内存压力
  选择当前更合适的兼容节点。
- Alembic 首版迁移，以及升级、回滚和 ORM 模型一致性测试。
- LibreOffice 旧格式升级工具及异常、超时和输出校验测试。
- 按控制面、接入协议、硬件 Worker 和 Ray Serve 拆分的 Python 依赖 Profile。
- CPU Dockerfile 中已声明 LibreOffice、FFmpeg/ffprobe 和中文字体系统依赖。

完整进度以 [TODO.md](TODO.md) 为准。

## 项目结构

```text
parser_serve/
├── api/            # HTTP 接入与中间件
├── backends/       # 文本、媒体及后续 OCR/VLM/ASR 实现
├── control/        # Pipeline 路由和 Stage 调度
├── domain/         # 状态机和领域规则
├── persistence/    # 数据库模型、会话和仓储
├── schema/         # 所有边界协议的唯一类型来源
├── storage/        # 本地及对象存储统一接口
├── worker/         # 拉取式 Worker Agent、客户端和预处理器
└── utils/          # LibreOffice 等无状态系统工具
migrations/         # Alembic 数据库迁移
docs/               # 架构和依赖文档
tests/              # 单元与契约测试
web/                # Vue 3 + shadcn-vue 管理控制台
```

后续继续增加 OCR/VLM/ASR Backend、生产队列、对象存储和各硬件 Worker 镜像。

## 开发环境

支持 Python 3.12 和 3.13，推荐使用 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --extra control-plane
```

运行 API：

```bash
PARSER_SERVE_API_KEYS='["parser_replace_with_a_real_secret"]' \
uv run --extra control-plane \
uvicorn parser_serve.app:app --reload
```

未配置 API Key 时，健康检查仍可访问，但受保护接口不会接受任何凭证。

本地开发默认将上传内容写入 `./data/storage`，可通过
`PARSER_SERVE_LOCAL_STORAGE_PATH` 修改。生产多机部署使用
`PARSER_SERVE_STORAGE_BACKEND=s3` 切换到共享 S3/MinIO，不能让多个控制面
实例依赖各自的本地磁盘。完整配置见 [Storage 配置](docs/storage.md)。
S3/MinIO Artifact 还可通过普通 API Key 获取短期签名下载 URL；本地 Storage
继续使用带 API Key 的流式内容接口。

多控制面部署可启用 Redis Streams Stage 可用性通知：

```bash
PARSER_SERVE_TASK_QUEUE_BACKEND=redis_streams \
PARSER_SERVE_REDIS_URL=redis://redis:6379/0 \
uv run --extra control-plane uvicorn parser_serve.app:app
```

Redis 只用于唤醒 Worker 的长轮询请求；Stage 状态、租约令牌摘要、续租和
幂等结果仍以数据库为准。Redis 故障时服务自动退化为周期性数据库轮询。
完整边界和配置见[任务队列与多机派发](docs/task-queue.md)。

控制面默认保留上传文件 1 天、Artifact 30 天、事件 7 天，并每 5 分钟分批
执行清理。普通 API Key 可通过
`POST /api/v1/management/maintenance/retention/run` 先试运行，再执行一次
清理；Web UI 的“系统信息”页提供同一能力。完整语义和配置见
[数据保留与清理](docs/retention.md)。

上传后使用返回的 `file_id` 创建解析任务：

```bash
curl -H "Authorization: Bearer ${PARSER_SERVE_API_KEY}" \
  -F "file=@example.doc" \
  http://127.0.0.1:8000/api/v1/files

curl -H "Authorization: Bearer ${PARSER_SERVE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"source":{"type":"uploaded_file","file_id":"file_replace_me"}}' \
  http://127.0.0.1:8000/api/v1/tasks
```

运行 CPU Worker：

```bash
PARSER_WORKER_CONTROL_PLANE_URL=http://127.0.0.1:8000 \
PARSER_WORKER_API_KEY=parser_replace_with_worker_key \
PARSER_WORKER_WORKER_ID=worker_cpu00001 \
uv run --extra worker-cpu parser-worker-cpu
```

Worker 默认使用最长 20 秒的租约长轮询，可通过
`PARSER_WORKER_LEASE_WAIT_SECONDS` 在 `0..30` 秒内调整；设为 `0` 时使用
传统短轮询。

CPU Worker 始终上报 `builtin_text` 和 `builtin_web`。仅当启动时检测到 `ffmpeg` 和
`ffprobe` 时才上报 `builtin_ffmpeg`，避免调度到缺少系统依赖的节点。
`builtin_pdf` 和 `builtin_image` 分别由 CPU Profile 中的 pypdf 与 Pillow
提供，`builtin_web` 使用标准库解析静态 HTML。
LibreOffice 不可用时，Worker 的 `builtin_office` 能力会移除 `.doc/.ppt/.xls`
对应 MIME，调度器同时校验 Worker 实际上报的 MIME，而不是只比较 Backend
名称。已在注册时使用的 LibreOffice、FFmpeg/ffprobe 会在每次心跳复检；
依赖丢失时先发送带类型化 Health Check 的 `unhealthy` 心跳，再停止领取任务。
旧 Office 文件进入真正的文档 Backend 前仍只由预处理器升级格式。

Worker 设备通过统一探测协议注册：CPU 和 NVIDIA 提供内置探测，Ascend、
MLU、DCU、MUSA、XPU 可接入返回严格 JSON 的厂商探测命令。生产 CUDA
Worker 默认要求 `nvidia-smi` 探测成功；协议和失败策略见
[硬件探测协议](docs/hardware-probes.md)。

事件与回调：

```text
GET  /api/v1/events
GET  /api/v1/events/stream
GET  /api/v1/tasks/{task_id}/events
GET  /api/v1/tasks/{task_id}/events/stream
GET  /api/v1/management/callbacks
GET  /api/v1/management/callbacks/{delivery_id}
GET  /api/v1/management/callbacks/{delivery_id}/attempts
POST /api/v1/management/callbacks/{delivery_id}/retry
POST /api/v1/management/callbacks/test
```

任务执行详情与结果：

```text
GET /api/v1/tasks/{task_id}/stages
GET /api/v1/tasks/{task_id}/stages/{stage_id}
GET /api/v1/tasks/{task_id}/result
GET /api/v1/tasks/{task_id}/result/content
```

`/result` 只接受 Worker 上传并登记为主结果 Artifact 的标准
`ParseResult` JSON，且受 `PARSER_SERVE_MAXIMUM_RESULT_JSON_BYTES` 限制；
`/result/content` 用于流式下载原始主结果。

SSE 使用与业务接口相同的普通 API Key，并支持标准 `Last-Event-ID` Header。
启用后台回调投递器需设置
`PARSER_SERVE_CALLBACK_DISPATCHER_ENABLED=true`。签名 Header 为
`X-Parser-Signature: v1=<hex>`，签名内容是
`<X-Parser-Timestamp>.<原始请求体>`。接收方应按 `event_id` 幂等处理。
当前 URL 校验和禁重定向是应用层保护；生产环境还应通过出口代理或网络策略
阻止 DNS 重绑定后访问内网。

URL Source 抓取发生在 Worker，不发生在 API 进程。Worker 拒绝凭证 URL、
localhost、非公网或混合 DNS 结果、HTTPS 降级、非网页 MIME 和超限响应，
每次重定向都会重新校验。生产环境仍需通过 Worker 出口网络策略防止 DNS
重绑定；限制可通过 `PARSER_WORKER_MAXIMUM_URL_DOWNLOAD_BYTES`、
`PARSER_WORKER_URL_DOWNLOAD_TIMEOUT_SECONDS` 和
`PARSER_WORKER_MAXIMUM_URL_REDIRECTS` 配置。
CPU 解析还会强制执行
`PARSER_WORKER_MAXIMUM_PDF_PAGES`、
`PARSER_WORKER_MAXIMUM_IMAGE_PIXELS` 和
`PARSER_WORKER_MAXIMUM_MEDIA_DURATION_SECONDS`。这些是 Worker 安全上限，
Pipeline Stage 参数只能收紧，不能放宽；所有 Backend 执行受 Stage
`timeout_seconds` 约束。

MCP 使用 `POST /mcp` 和普通 API Key，支持 Bearer Header 以及
`X-API-Key`。默认只接受本机 Host/Origin；反向代理部署时必须通过
`PARSER_SERVE_MCP_ALLOWED_HOSTS` 和
`PARSER_SERVE_MCP_ALLOWED_ORIGINS` 配置实际域名（Pydantic Settings 的
JSON 数组格式）。MCP 不直接传输大型文件，先调用 HTTP 文件上传接口，再在
`parser_submit` 中传入 `uploaded_file` Source。

常用检查：

```bash
uv run --extra control-plane ruff format --check .
uv run --extra control-plane ruff check .
uv run --extra control-plane pyright
uv run --extra control-plane pytest --cov=parser_serve
```

Web UI 源码位于 `web/`，当前已提供连接页、系统总览、文本、文件、网页 URL
和 S3/MinIO 解析测试，支持 Pipeline、Backend、Runtime 偏好、解析特性、
请求 JSON 与 cURL 预览，以及任务列表、Worker Drain、Backend 注册/启停、
Pipeline 草稿/校验/发布、
回调测试/重试、API Key 创建/轮换/启停/删除和系统信息页面。看板覆盖任务、
Worker、Backend、在线硬件 Runtime 和失败回调。API Key 默认仅保存于当前
浏览器会话。任务详情页通过带 `Authorization` 和 `Last-Event-ID` 请求头的
流式 Fetch 展示 Stage 实时进度，断线时自动续传并以轮询兜底；页面支持
ParseResult JSON、文本、表格、Transcript/Keyframe 时间轴，以及带鉴权的
文本、Markdown、JSON、图片、音频、视频和 PDF Artifact 预览与下载；可执行
状态的任务可取消，失败或取消的任务可从详情页重试。
看板统计来自开放的
`GET /api/v1/management/dashboard/summary`，支持时间窗口以及 Pipeline、
Backend、Worker、Runtime 和媒体类型过滤，其他系统可以使用同一普通 API Key
直接集成任务成功率、延迟分位数、资源、回调和存储指标。
控制面同时提供需普通 API Key 的 `GET /metrics` Prometheus 端点；HTTP、
Task、Stage、Worker、Backend、Callback 和 Storage 指标及 JSON 日志字段见
[可观测性说明](docs/observability.md)。
首次安装前端依赖后可运行：

```bash
cd web
npm run generate:api
npm run dev
```

`generate:api` 从 FastAPI OpenAPI 生成完整 TypeScript Schema、operationId
类型、运行时路由表和零依赖 Client；`npm run check:api` 检查生成产物是否
漂移，`npm run check:sdk` 单独执行严格 TypeScript 检查。独立域名部署时通过
`PARSER_SERVE_CORS_ALLOWED_ORIGINS` 配置准确的 Web UI Origin，禁止使用
通配符。按照当前实施约束，本阶段未安装前端依赖、未运行构建或发布。

外部 Python 系统可安装轻量 SDK Profile：

```bash
uv sync --frozen --no-dev --extra python-sdk
```

`parser_serve.sdk` 提供同步和异步 Client，复用 `schema` 类型，并由 OpenAPI
生成全部 operationId 路由。常用任务、上传和结果操作有直接类型化方法，其他
管理和 Worker 接口可通过生成的 operationId 调用。详见
[Python SDK](docs/python-sdk.md)。

## 数据库迁移

默认连接仅用于本地示例。部署时通过 `PARSER_SERVE_DATABASE_URL` 指定数据库，并在控制面启动前单独执行迁移：

```bash
PARSER_SERVE_DATABASE_URL='postgresql+asyncpg://user:password@host/database' \
uv run --extra control-plane alembic upgrade head
```

应用进程不会在启动时自动建表或执行迁移。

完成迁移后，可使用普通 API Key 幂等初始化内置 Backend 与默认 Pipeline：

```bash
curl -X POST http://localhost:8000/api/v1/management/defaults/initialize \
  -H 'Authorization: Bearer parser_replace_with_api_key' \
  -H 'Content-Type: application/json' \
  -d '{"include_builtin_backends":true,"publish_valid_pipelines":true}'
```

初始化会创建 `document.auto`、`web.static`、`web.rendered`、`image.ocr`、
`image.multimodal`、`audio.transcription` 和 `video.multimodal`。只有通过
Backend 能力校验的 Pipeline 才会发布；尚未接入动态网页渲染、OCR、ASR 或
VLM 时，对应 Pipeline 保持 Draft，响应中包含完整的类型化校验错误。

管理系统可以对 Draft 或 Published 指定版本创建真实测试任务：

```bash
curl -X POST \
  http://localhost:8000/api/v1/management/pipelines/pipeline_web_static/versions/1/test \
  -H 'Authorization: Bearer parser_replace_with_api_key' \
  -H 'Content-Type: application/json' \
  -d '{
    "source":{"type":"url","url":"https://example.com"},
    "options":{"priority":10},
    "client_reference":"pipeline-smoke-test"
  }'
```

返回标准 `TaskDetailResponse`，可继续通过任务详情、SSE 和结果接口观察执行。
请求失败不会残留 Task，测试也不会发布或修改 Pipeline。

创建任务时控制面会在同一事务内尝试生成 Stage 计划；如果当时尚无兼容
Pipeline 或 Backend，任务保持 Pending 且不会提交部分 Stage。后台路由服务
持续重试，因此后续注册模型能力后无需重新提交任务。

普通 API Key 也可以通过 `GET/PATCH /api/v1/management/settings` 管理已经
接入运行链路的动态设置。首批包括最大上传字节数、最大结果 JSON 字节数和
回调最大尝试次数；数据库覆盖值在多控制面副本间共享并对后续请求立即生效。
驱动、模型目录、数据库地址等部署级参数仍由镜像和环境变量管理。

## 依赖与镜像

控制面和各硬件 Worker 不共用大型运行时依赖：

```bash
uv sync --frozen --no-dev --extra control-plane
uv sync --frozen --no-dev --extra worker-cpu
uv sync --frozen --no-dev --extra worker-cuda
uv sync --frozen --no-dev --extra worker-ascend
uv sync --frozen --no-dev --extra worker-cpu --extra object-storage
```

硬件 Worker Profile 互斥；Ray Serve 是可与一个 Worker Profile 组合的可选执行器。LibreOffice、FFmpeg、显卡驱动和厂商运行时属于镜像系统依赖，不写入 `pyproject.toml`。

仓库已分别提供控制面、Web、CPU、CUDA、Ascend、MLU、DCU、MUSA 和 XPU
Dockerfile。CUDA 与国产硬件镜像必须显式传入经过验证的厂商基础镜像，不
设置会掩盖运行时缺失问题的通用默认值。当前仅完成定义和静态契约测试，
未拉取镜像或执行构建。

Object Storage 是与硬件无关的可组合 Profile。启用后通过
`PARSER_WORKER_ALLOWED_S3_BUCKETS` 配置 JSON Bucket 白名单；MinIO 可另设
`PARSER_WORKER_S3_ENDPOINT_URL`，认证沿用 boto3 标准环境变量或实例身份。
默认空白名单意味着禁用任意对象读取。

## 文档

- [总体架构规划](docs/architecture-plan.md)
- [依赖 Profile 与镜像构建说明](docs/dependency-profiles.md)
- [容器镜像说明](docs/container-images.md)
- [Kubernetes 与 Helm 部署](docs/kubernetes.md)
- [Docker Compose 本地部署](docs/local-compose.md)
- [任务队列与多机派发](docs/task-queue.md)
- [Worker Backend 模型生命周期与多设备执行](docs/backend-lifecycle.md)
- [可选 Ray Serve Executor](docs/ray-serve.md)
- [事件总线与实时流](docs/events.md)
- [HTTP API 集成](docs/api-integration.md)
- [Python SDK](docs/python-sdk.md)
- [TypeScript SDK](docs/typescript-sdk.md)
- [错误响应与稳定错误码](docs/error-codes.md)
- [Callback 接入与幂等](docs/callbacks.md)
- [解析引擎接入](docs/engine-backends.md)
- [默认 Pipeline 与端到端样本](docs/default-pipelines.md)
- [输入内容安全](docs/input-security.md)
- [可观测性](docs/observability.md)
- [数据保留与清理](docs/retention.md)
- [版本与兼容策略](docs/versioning.md)
- [远程 Backend 接入协议](docs/remote-backends.md)
- [实施 TODO](TODO.md)

## 安全边界

解析服务会处理不受信任的文件和 URL。生产实现必须联合校验扩展名、MIME 和内容签名，限制文件大小、页数、媒体时长及执行资源，并防护 SSRF、压缩炸弹、路径穿越和恶意文档。系统工具应在隔离的 Worker 子进程或容器内运行，日志不得记录原始密钥和敏感内容。

## License

项目暂未声明开源许可证。如需分发或商用，请先确认授权方式。
