# Docker Compose 本地部署

仓库根目录的 `compose.yaml` 提供一套可审计的本地多进程环境。当前只提交
编排文件，不在实现阶段拉取镜像或执行构建。

## 默认服务

```text
web :8080
  └─ Nginx 同源代理
      └─ control-plane :8000
          ├─ PostgreSQL
          ├─ Redis Streams
          └─ MinIO
                 ↑
            worker-cpu
```

启动顺序由健康检查约束：

1. PostgreSQL、Redis 和 MinIO 就绪；
2. `minio-init` 幂等创建 `parser-serve` Bucket；
3. `migrate` 执行 `alembic upgrade head`；
4. 控制面 `/ready` 通过；
5. `catalog-init` 幂等初始化内置 Backend 和默认 Pipeline；
6. Web 与 Worker 开始服务。

## 配置

复制示例配置并替换所有开发凭证：

```bash
cp .env.example .env
```

`.env` 和 `compose.override.yaml` 已被 Git 忽略，`.env.example` 保留为类型和变量
清单。默认示例密钥只能用于一次性本地环境，不能用于共享测试或生产。

主要端口：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `PARSER_API_PORT` | `8000` | 控制面直接访问 |
| `PARSER_WEB_PORT` | `8080` | Web UI 与同源 API |
| `MINIO_CONSOLE_PORT` | `9001` | MinIO 管理台 |

未来允许构建时可执行：

```bash
docker compose --env-file .env up --build
```

Web UI 使用 `http://localhost:8080`，连接 API 时保持同一地址，并填写
`.env` 中的 `PARSER_SERVE_API_KEY`。Nginx 会代理 `/api`、`/health`、
`/ready`、`/metrics` 和 `/mcp`，并关闭缓冲以支持 SSE。Prometheus 抓取
`http://localhost:8080/metrics` 时必须携带同一个普通 API Key：

```yaml
authorization:
  type: Bearer
  credentials: parser_replace_me
```

详细指标和日志字段见[可观测性](observability.md)。

停止服务但保留数据：

```bash
docker compose down
```

删除命名卷会永久删除 PostgreSQL、Redis 和 MinIO 数据，应只在明确需要重置
本地环境时执行。

## 硬件 Profiles

CPU Worker 默认启用。所有 Worker 同时连接内部服务网络和一个不发布 Worker
端口的出站网络，以支持 URL Source、回调模型服务和对象源访问。其他 Runtime
使用独立 Profile 和 Dockerfile：

```bash
docker compose --profile cuda up --build
docker compose --profile ascend up --build
docker compose --profile mlu up --build
docker compose --profile dcu up --build
docker compose --profile musa up --build
docker compose --profile xpu up --build
```

启用前必须在 `.env` 设置对应的厂商基础镜像，例如
`CUDA_BASE_IMAGE` 或 `ASCEND_BASE_IMAGE`。国产硬件还应设置返回
`HardwareProbeSnapshot 1.0` 的 `*_DEVICE_PROBE_COMMAND`，并通过本地
`compose.override.yaml` 添加厂商要求的设备映射、共享内存、驱动目录和模型
缓存。基础 Compose 不猜测宿主机 `/dev` 路径，也不授予 `privileged`。

引擎服务配置使用对应的 `*_ENGINE_BACKENDS` JSON，例如：

```text
CUDA_ENGINE_BACKENDS=[
  {"engine":"paddleocr","endpoint":"http://paddleocr:8080/v1/parse"}
]
```

实际模型服务需要加入 `parser-internal` 网络，或通过明确的外部网络 Override
访问。配置格式见[解析引擎接入](engine-backends.md)。

## 生产边界

该 Compose 面向本地开发和单机集成测试。生产部署还必须：

- 使用 Secret 管理器，不通过环境文件分发长期密钥；
- 固定镜像摘要并完成漏洞扫描和签名；
- 使用托管或高可用 PostgreSQL、Redis 和对象存储；
- 独立执行数据库迁移并制定回滚步骤；
- 为内部 Worker API、数据库、Redis、MinIO 和模型服务配置网络策略；
- 使用 Kubernetes/调度平台声明厂商设备资源、Node Selector 与滚动升级策略。
