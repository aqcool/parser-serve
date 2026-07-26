# 可选 Ray Serve Executor

Ray Serve 用于某个模型服务集群内部的模型常驻、GPU Replica、自动扩缩、排队
和模型组合。Parser Serve 仍负责全局 Task/Pipeline、异构 Worker 选择、租约、
重试、回调和 Artifact；Ray Serve 不替代控制面的权威调度。

实现遵循 Ray Serve 当前 `Deployment.bind()` 应用、异步
`DeploymentHandle.remote()` 和每个 Deployment 的
`max_ongoing_requests`/`max_queued_requests` 模型。生产 Kubernetes 环境可把
该应用交给 KubeRay RayService 管理。

## 安装

Ray 模型服务镜像选择一个硬件 Profile，并增加：

```bash
uv sync --frozen --no-dev \
  --extra worker-cuda \
  --extra ray-serve
```

该 Profile 包含 `ray[serve]` 和 multipart 解析依赖，不进入控制面或普通
Worker 镜像。

## 模型 Handler

模型适配器实现严格的异步协议：

```python
class MyModel:
    def __init__(self) -> None:
        self.model = load_model_once()

    async def parse(
        self,
        request: RemoteParseRequest,
        file_content: bytes | None,
    ) -> RemoteParseResponse:
        # 构造符合 schema.remote.RemoteParseResponse 的结果
        ...
```

每个 Ray Replica 构造一次 Handler，因此可在 `__init__` 中常驻模型。不要在
每个请求中重新加载权重。

建立应用：

```python
from pydantic import SecretStr

from parser_serve.ray_serve import (
    RayServeDeploymentConfig,
    build_ray_serve_application,
)

app = build_ray_serve_application(
    MyModel,
    config=RayServeDeploymentConfig(
        num_replicas=2,
        max_ongoing_requests=1,
        max_queued_requests=8,
        num_cpus=4.0,
        num_gpus=1.0,
        maximum_file_bytes=256 * 1024 * 1024,
        bearer_token=SecretStr("replace-with-model-service-token"),
    ),
)
```

开发启动：

```bash
serve run my_ray_app:app
```

然后把 Worker 的 `PARSER_WORKER_ENGINE_BACKENDS` 或
`PARSER_WORKER_REMOTE_BACKENDS` Endpoint 指向该应用根路径。生产部署应使用
Ray Serve 配置或 KubeRay RayService，而不是让 Parser Serve 控制面直接启动
Ray 集群。

## 协议和保护

Ingress 原生实现 [Remote Backend 1.0](remote-backends.md) multipart 协议：

- 请求 JSON 在调用模型前由 `RemoteParseRequest` 校验；
- multipart 请求体在解析前采用有界分块读取，并提前检查 `Content-Length`；
- 文件再次执行独立大小限制，并校验协议声明大小和 SHA-256；
- Handler 响应由判别联合 Schema 校验；
- 校验 Task ID 和不可变 SourceMetadata；
- 超时映射为可重试 `TIMEOUT`，内部异常不返回 traceback 或模型密钥；
- 可选 Bearer Token 使用常量时间比较；
- Worker 传来的 `runtime` 和 `device_id` 保留给 Handler。
- Ingress 从 HTTP `traceparent` 接续 Worker Span；Header 缺失时回退到协议中
  持久化的 Trace Context，并为 Handler 创建 `parser.remote.execute` Span。

应用层请求体上限包含 `maximum_file_bytes`、最多 1 MiB 的协议 JSON 和少量
multipart framing 余量。生产入口仍必须在 Ingress、Gateway 或 Service Mesh
配置同量级的请求体上限，使超限流量在到达 Ray Replica 前被拒绝。

`max_ongoing_requests` 控制每 Replica 并发，`max_queued_requests` 提供负载
丢弃边界，Worker 自身 Backend 信号量和 Stage 超时仍同时生效。对于跨多机
Ray 集群，实际物理 GPU 由 Ray Replica 资源调度决定，Parser Serve 的
`device_id` 用作准入和追踪信息；只有 Ray 与 Worker 共进程/同设备绑定时才应
直接用它选择厂商设备。

官方参考：

- [Ray Serve DeploymentHandle 与模型组合](https://docs.ray.io/en/latest/serve/model_composition.html)
- [Ray Serve 生产最佳实践](https://docs.ray.io/en/latest/serve/production-guide/best-practices.html)
- [Ray Serve 生产部署与 KubeRay](https://docs.ray.io/en/latest/serve/production-guide/index.html)
