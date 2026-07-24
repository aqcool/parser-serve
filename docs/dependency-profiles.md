# 依赖 Profile 与镜像构建说明

## 1. 目标

Parser Serve 将控制面、接入协议和不同硬件 Worker 的 Python 依赖分开管理，避免所有组件安装同一套大型依赖。

依赖拆分需要满足：

- 控制面不安装 GPU 推理框架。
- CPU Worker 不安装任何厂商 GPU SDK。
- CUDA、Ascend、MLU、DCU、MUSA 和 XPU 使用独立依赖 Profile。
- Ray Serve 是可选执行器，不强制安装到所有 Worker。
- LibreOffice、FFmpeg、显卡驱动和厂商运行时由 Dockerfile 安装，不作为 Python 包管理。LibreOffice 只作为 `.doc → .docx`、`.ppt → .pptx`、`.xls → .xlsx` 的转换工具，不属于解析 Backend。
- 所有生产镜像使用同一份 `uv.lock` 进行可重复安装。

## 2. Python 版本

项目当前声明：

```toml
requires-python = ">=3.12,<3.14"
```

本地开发默认使用 `.python-version` 中的 Python 3.13，当前 CPU Docker 基础镜像使用 Python 3.12。新增 Backend 前必须确认其 Python 包同时满足项目版本范围。

如果某个厂商 SDK 只能使用范围外的 Python 版本，应先评估：

1. 是否可以升级厂商 SDK；
2. 是否应调整整个项目的兼容范围；
3. 是否需要让该 Worker 使用独立发行包或协议客户端。

不要在 Dockerfile 中绕过 `requires-python` 强制安装。

## 3. 核心依赖

`[project.dependencies]` 只包含所有进程都会使用的依赖：

```toml
dependencies = [
    "pydantic>=2.13.4",
    "pydantic-settings>=2.14.2",
]
```

安装核心依赖：

```bash
uv sync --frozen --no-dev
```

核心依赖中不应加入：

- FastAPI 或 MCP 等特定入口依赖
- PostgreSQL、Redis 或 S3 客户端
- Ray Serve
- OCR、VLM 或 ASR 框架
- 任何硬件厂商 SDK

## 4. 接入方式 Profile

### 4.1 HTTP API

Profile：

```text
http-api
```

包含 FastAPI 及其标准运行依赖：

```bash
uv sync --frozen --no-dev --extra http-api
```

适用于只需要 HTTP 接入、不运行完整调度控制面的轻量进程。

### 4.2 MCP

Profile：

```text
mcp
```

安装：

```bash
uv sync --frozen --no-dev --extra mcp
```

适用于独立部署 MCP Gateway。MCP 与 HTTP API 应复用相同的 `schema` 和 Service，不单独实现解析逻辑。

控制面当前在 `/mcp` 暴露无状态 Streamable HTTP MCP。默认 Host/Origin
allowlist 仅包含 loopback；容器或反向代理部署需要设置
`PARSER_SERVE_MCP_ALLOWED_HOSTS` 与
`PARSER_SERVE_MCP_ALLOWED_ORIGINS`。大型文件仍通过 HTTP 上传，MCP 只传
`file_id`。

### 4.3 Object Storage

```bash
uv sync --extra worker-cpu --extra object-storage
uv sync --extra worker-cuda --extra object-storage
```

`object-storage` 只包含 boto3，可与任一硬件 Worker Profile 组合，不属于
CUDA、Ascend 等硬件互斥组。Worker 使用标准 AWS 凭证链，并必须配置
`PARSER_WORKER_ALLOWED_S3_BUCKETS`；空白名单关闭对象读取。MinIO 通过
`PARSER_WORKER_S3_ENDPOINT_URL` 接入，源码协议仍统一使用
`s3://bucket/key`。

### 4.4 Python SDK

Profile：

```text
python-sdk
```

安装：

```bash
uv sync --frozen --no-dev --extra python-sdk
```

该 Profile 只增加 `httpx`，用于外部系统调用同步或异步 Python SDK。SDK
复用基础依赖中的 Pydantic Schema，不安装 FastAPI、数据库、队列或模型
运行时。使用说明见 [Python SDK](python-sdk.md)。

### 4.5 完整控制面

Profile：

```text
control-plane
```

包含：

- FastAPI
- MCP
- PostgreSQL 和数据库迁移
- Redis Streams
- S3/MinIO 客户端
- HTTP 回调客户端

安装：

```bash
uv sync --frozen --no-dev --extra control-plane
```

完整控制面不应再组合任何硬件 Worker Profile。控制面和 Worker 即使部署在同一台机器，也推荐使用独立进程和镜像。

Redis Streams 是可选的 Stage 可用性通知层。使用
`PARSER_SERVE_TASK_QUEUE_BACKEND=redis_streams` 启用；数据库仍保存权威租约，
Redis 故障时自动降级为数据库轮询。详见[任务队列与多机派发](task-queue.md)。

### 4.6 OpenTelemetry

```bash
uv sync --frozen --no-dev \
  --extra control-plane \
  --extra telemetry
```

Worker 镜像同样可以把 `telemetry` 与且仅与一个硬件 Profile 组合。该 Profile
包含 OpenTelemetry SDK、OTLP/HTTP Exporter、FastAPI 和 HTTPX
Instrumentation，不进入基础依赖。配置和跨异步任务传播见
[可观测性说明](observability.md)。

## 5. Worker Profile

每个生产 Worker 镜像必须且只能选择一个硬件 Profile。

| 硬件 | Profile | 示例命令 |
| --- | --- | --- |
| CPU | `worker-cpu` | `uv sync --frozen --no-dev --extra worker-cpu` |
| NVIDIA CUDA | `worker-cuda` | `uv sync --frozen --no-dev --extra worker-cuda` |
| 华为 Ascend | `worker-ascend` | `uv sync --frozen --no-dev --extra worker-ascend` |
| 寒武纪 MLU | `worker-mlu` | `uv sync --frozen --no-dev --extra worker-mlu` |
| 海光 DCU | `worker-dcu` | `uv sync --frozen --no-dev --extra worker-dcu` |
| 摩尔线程 MUSA | `worker-musa` | `uv sync --frozen --no-dev --extra worker-musa` |
| 昆仑芯 XPU | `worker-xpu` | `uv sync --frozen --no-dev --extra worker-xpu` |

当前各硬件 Worker Profile 只包含 Worker 与控制面通信所需的 HTTP 客户端。厂商 SDK 和推理框架将在对应 Backend 实现时加入。具体 Dockerfile、厂商基础镜像参数和设备声明见 [容器镜像说明](container-images.md)。

通用 Worker 入口为 `parser-worker`；`parser-worker-cpu` 作为兼容别名保留。
CPU Worker 启动示例：

```bash
PARSER_WORKER_CONTROL_PLANE_URL=http://control-plane:8000 \
PARSER_WORKER_API_KEY=parser_replace_with_worker_key \
PARSER_WORKER_WORKER_ID=worker_cpu00001 \
uv run --extra worker-cpu parser-worker
```

Worker 启动时探测 LibreOffice、FFmpeg、ffprobe、pypdf 和 Pillow，不会把
不存在的工具或 Python 依赖能力上报给控制面。LibreOffice 仍然只是旧
Office 格式预处理工具，不会出现在 Backend Registry；`builtin_ffmpeg`
只在 ffmpeg 与 ffprobe 同时可用时上报。pypdf 和 Pillow 仅属于
`worker-cpu` Profile，分别为 `builtin_pdf` 与 `builtin_image` 提供能力。

### 5.1 硬件 Profile 互斥

`[tool.uv].conflicts` 声明所有硬件 Profile 互斥。因此以下命令应失败：

```bash
uv sync --extra worker-cpu --extra worker-cuda
```

互斥规则可以防止：

- CPU 和 CUDA 推理包进入同一生产镜像
- 多个厂商 SDK 产生动态链接库冲突
- 锁文件错误选择不匹配的推理框架版本
- 镜像无法明确表达自身硬件能力

## 6. Ray Serve

Profile：

```text
ray-serve
```

Ray Serve 是 Worker 的可选执行器，可以与任意一个硬件 Worker Profile 组合：

```bash
uv sync --frozen --no-dev \
  --extra worker-cuda \
  --extra ray-serve
```

Ray Serve 不属于核心依赖，也不默认安装到控制面。全局任务调度由 Parser
Serve Scheduler 负责，Ray Serve 只管理某个 Worker 或集群内部的模型执行。
仓库提供 Remote Backend 1.0 Ingress、文件完整性和大小校验、类型化错误、
Bearer 认证、Replica 资源与背压配置，见
[可选 Ray Serve Executor](ray-serve.md)。

## 7. 开发依赖

开发工具使用 `[dependency-groups].dev`：

```bash
uv sync --extra control-plane
```

`uv sync` 默认包含开发组。生产镜像必须显式增加：

```text
--no-dev
```

当前开发组包括：

- Pytest
- pytest-cov
- Pyright
- Ruff

常用命令：

```bash
uv run pytest
uv run pytest --cov=parser_serve
uv run pyright
uv run ruff check .
uv run ruff format --check .
```

数据库迁移命令需要 `control-plane` Profile：

```bash
uv run --extra control-plane alembic upgrade head
uv run --extra control-plane alembic downgrade -1
uv run --extra control-plane alembic current
```

默认数据库连接只用于本地示例。部署时应通过发布配置覆盖 Alembic 的 `sqlalchemy.url`，并在启动控制面前单独执行迁移；应用进程不自动执行迁移。

## 8. Python 依赖与系统依赖的边界

### 8.1 Python 依赖

写入 `pyproject.toml`：

- FastAPI、MCP
- 数据库和消息队列客户端
- 对象存储客户端
- Python OCR、ASR 和 VLM 包
- Python 推理框架
- Backend 使用的 Python SDK

### 8.2 系统依赖

写入对应 Dockerfile：

- LibreOffice
- FFmpeg 和 ffprobe
- 字体
- 浏览器和浏览器系统库
- NVIDIA CUDA Runtime
- Ascend CANN
- MLU Neuware
- DCU、MUSA、XPU 厂商运行时
- 编译工具和系统动态链接库

系统依赖不能通过 `pyproject.toml` 表示。安装 Python 厂商包也不代表镜像已经具备对应驱动和运行时。

## 9. Backend 依赖归属

新增 Backend 时，先判断它运行在哪些硬件平台。

### 9.1 仅 CPU

例如一个只支持 CPU 的文档解析包：

```toml
worker-cpu = [
    "httpx>=0.28",
    "example-document-parser>=1.0",
]
```

### 9.2 CUDA 专用

```toml
worker-cuda = [
    "httpx>=0.28",
    "example-cuda-runtime>=1.0",
]
```

CUDA 专用包不得加入 `dependencies`、`control-plane` 或 `worker-cpu`。

### 9.3 多硬件实现

如果 PaddleOCR 等能力在多个平台有不同运行包，应分别加入对应 Profile：

```text
worker-cpu     → CPU 推理包
worker-cuda    → CUDA 推理包
worker-ascend  → Ascend 适配包
```

Backend 名称可以相同，但 Worker 注册时必须上报实际运行时、包版本和 Backend 版本。

### 9.4 远程服务接入

如果 MinerU、HunyuanOCR 或其他能力通过远程 HTTP 服务接入，调用客户端通常只需要 `httpx`，不应把服务端模型依赖安装到调用方镜像。

远程 Backend 使用统一的 `RemoteHttpBackend` 和强类型 1.0 协议，配置与
服务端契约见 [远程 Backend 接入协议](remote-backends.md)。本地 Backend
和远程 Backend 仍应使用不同实现：

```text
MinerULocalBackend
RemoteHttpBackend(name="mineru")
```

## 10. 添加新依赖的流程

1. 确认依赖属于核心、控制面、接入协议、Worker 还是开发工具。
2. 确认支持的 Python 版本、操作系统和 CPU 架构。
3. 对硬件包确认驱动和运行时兼容矩阵。
4. 只修改对应的 dependency Profile。
5. 更新锁文件：

   ```bash
   uv lock
   ```

6. 验证目标组合：

   ```bash
   uv sync --no-dev --extra worker-cuda --dry-run
   ```

7. 验证互斥 Profile 仍不能同时安装。
8. 在目标镜像中执行导入检查和 Backend 健康检查。
9. 运行单元测试和目标硬件端到端测试。
10. 更新本文档和 TODO。

## 11. Dockerfile 使用方式

仓库已经提供不同职责和硬件的独立 Dockerfile，完整列表和构建参数见
[容器镜像说明](container-images.md)。不同镜像使用不同 extra。示意：

```dockerfile
RUN uv sync \
    --frozen \
    --no-dev \
    --extra worker-cpu
```

CUDA Worker 的实际 Dockerfile 不默认组合 `ray-serve`；需要时应建立明确的
派生构建目标。依赖组合示意：

```dockerfile
RUN uv sync \
    --frozen \
    --no-dev \
    --extra worker-cuda \
    --extra ray-serve
```

为了提高构建缓存命中率，Dockerfile 应先复制：

```text
pyproject.toml
uv.lock
```

完成依赖安装后再复制应用源代码。

## 12. 验证矩阵

每次修改依赖后至少验证：

| 组合 | 必须通过 |
| --- | --- |
| 核心 | 解析和安装成功 |
| `control-plane` | 解析、导入和 API 启动成功 |
| `worker-cpu` | 解析、导入和 CPU 健康检查成功 |
| 当前主力 GPU Worker | 解析、导入和设备健康检查成功 |
| Worker + `ray-serve` | 解析和 Ray 启动成功 |
| 两个硬件 Worker Profile | 必须因互斥规则失败 |

锁文件检查：

```bash
uv lock --check
```

格式和测试：

```bash
uv run ruff check .
uv run pyright
uv run pytest
```
