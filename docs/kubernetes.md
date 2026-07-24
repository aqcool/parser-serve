# Kubernetes 与 Helm 部署

仓库提供 `deploy/helm/parser-serve` Chart。它部署控制面、Web UI、数据库迁移
Hook，以及按 Runtime 分离的 CPU、CUDA、Ascend、MLU、DCU、MUSA 和 XPU
Worker Deployment。Chart 不内置 PostgreSQL、Redis 或 MinIO，生产环境应使用
独立托管实例或平台级 Operator。

## 前置条件

- Kubernetes 1.28 或更高版本；
- 已推送与目标硬件匹配的独立镜像；
- PostgreSQL、Redis 和 S3/MinIO 可从命名空间访问；
- 加速卡节点已安装对应驱动、Device Plugin 和 RuntimeClass；
- 一个不由 Helm 保存明文凭据的 Secret。

Secret 默认名为 `parser-serve-secrets`，必须包含：

| Key | 内容 |
| --- | --- |
| `database-url` | `postgresql+asyncpg://...` |
| `api-key-list` | 普通 API Key JSON 数组 |
| `worker-api-key-list` | 控制面接受的 Worker API Key JSON 数组 |
| `worker-api-key` | Worker 使用的单个 Key |
| `s3-access-key-id` | S3/MinIO Access Key |
| `s3-secret-access-key` | S3/MinIO Secret Key |

示例命令只展示字段来源，不应把真实值写入仓库或 shell 历史：

```bash
kubectl -n parser-serve create secret generic parser-serve-secrets \
  --from-file=database-url=/secure/database-url \
  --from-file=api-key-list=/secure/api-key-list.json \
  --from-file=worker-api-key-list=/secure/worker-api-key-list.json \
  --from-file=worker-api-key=/secure/worker-api-key \
  --from-file=s3-access-key-id=/secure/s3-access-key-id \
  --from-file=s3-secret-access-key=/secure/s3-secret-access-key
```

## 硬件节点与镜像

每个 Worker Profile 有独立的镜像、Node Selector 和资源声明。先为节点设置
Runtime 标签：

```bash
kubectl label node cpu-node-1 parser-serve/runtime=cpu
kubectl label node gpu-node-1 parser-serve/runtime=cuda
```

`values.yaml` 默认只启用 CPU。启用 CUDA：

```yaml
workers:
  cuda:
    enabled: true
    image:
      repository: registry.example/parser-worker-cuda
      tag: "0.1.0"
    nodeSelector:
      parser-serve/runtime: cuda
    engineBackends:
      - engine: paddleocr
        endpoint: https://paddleocr.internal/v1/parse
      - engine: mineru
        endpoint: https://mineru.internal/v1/parse
```

默认加速卡资源名如下，必须按实际 Device Plugin 调整：

| Runtime | 默认资源名 |
| --- | --- |
| CUDA | `nvidia.com/gpu` |
| Ascend | `huawei.com/Ascend910` |
| MLU | `cambricon.com/mlu` |
| DCU | `hygon.com/dcu` |
| MUSA | `mthreads.com/vgpu` |
| XPU | `kunlunxin.com/xpu` |

厂商探测命令通过 `deviceProbeCommand` 配置，并可设置
`deviceProbeRequired: true`。未确认驱动、运行时和设备插件兼容矩阵前，不应
启用对应 Profile。

## 安装

先在独立 values 文件中覆盖镜像和外部服务：

```yaml
controlPlane:
  image:
    repository: registry.example/parser-control-plane
    tag: "0.1.0"
web:
  image:
    repository: registry.example/parser-web
    tag: "0.1.0"
config:
  redisUrl: redis://redis.database.svc:6379/0
  s3EndpointUrl: https://minio.storage.svc
  s3Bucket: parser-serve
```

再执行：

```bash
helm upgrade --install parser-serve deploy/helm/parser-serve \
  --namespace parser-serve \
  --create-namespace \
  --values production-values.yaml \
  --atomic \
  --timeout 15m
```

`pre-install,pre-upgrade` Hook 会使用控制面镜像运行
`alembic upgrade head`。迁移失败时主 Deployment 不会更新；`--atomic` 会让
Helm 回滚资源变更。控制面和 Web 使用 `maxUnavailable: 0`。

## 网络策略与内部 Worker API

Chart 可以创建三组 `NetworkPolicy`：

- Web 接受 Ingress Controller 或外部来源流量，只能访问控制面 `8000/TCP`
  和集群 DNS；
- 控制面只接受同一 Helm Release 的 Web、Worker，以及显式添加的来源；
- Worker 不提供服务并拒绝全部入站，只能访问控制面、集群 DNS、允许的公网
  和显式声明的私网依赖。

默认未启用策略，因为 Chart 无法从 Secret 中的数据库 URL 安全推导 Pod
Selector 或 CIDR。先确认 CNI 实际支持并执行 `NetworkPolicy`，再在生产
values 中显式开启：

```yaml
networkPolicy:
  enabled: true
  controlPlane:
    # 打开后必须声明 PostgreSQL、Redis 和 S3/MinIO 私网出口。
    restrictEgress: true
    allowPublicEgress: true
    additionalIngress:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: ingress-nginx
    additionalEgress:
      - to:
          - namespaceSelector:
              matchLabels:
                kubernetes.io/metadata.name: database
            podSelector:
              matchLabels:
                app.kubernetes.io/name: postgresql
        ports:
          - {protocol: TCP, port: 5432}
      - to:
          - namespaceSelector:
              matchLabels:
                kubernetes.io/metadata.name: cache
        ports:
          - {protocol: TCP, port: 6379}
  worker:
    allowPublicEgress: true
    additionalEgress:
      - to:
          - namespaceSelector:
              matchLabels:
                kubernetes.io/metadata.name: storage
            podSelector:
              matchLabels:
                app.kubernetes.io/name: minio
        ports:
          - {protocol: TCP, port: 9000}
```

公网出口规则排除 loopback、link-local、RFC1918、CGNAT、文档地址、组播和
IPv6 ULA 等不可作为外部解析目标的网段。它为 URL Source 和 Callback 的
应用层逐跳 DNS/IP 校验提供第二层防护：即使发生解析后 DNS 重绑定，CNI
仍应拒绝发往私网的连接。由于 `ipBlock` 在 Service DNAT 前后的行为依赖 CNI，
上线前必须在目标集群测试公网、私网、双栈和 Service 流量。

`NetworkPolicy` 只能进行 L3/L4 控制，不能识别 `/internal/v1/*` 路径。
外部入口只能指向 Web Service；Web Nginx 不代理 `/internal`。Worker 直接
访问 ClusterIP 控制面，并继续使用独立 Worker API Key、Key 类型校验和
`worker_id` 身份绑定。不要把 Control Plane Service 改成公网
`LoadBalancer`；确需直接开放管理 API 时，应在 API Gateway 显式拒绝
`/internal/*`。

启用后至少执行以下验证：

1. 从非本 Release Pod 访问控制面和 Worker 均失败；
2. Web 的普通 API、SSE 和 MCP 调用正常，但 `/internal/v1/*` 不可达；
3. Worker 能注册、心跳、拉取任务、下载源文件和上传 Artifact；
4. URL/Callback 能访问允许的公网，私网、link-local 和双栈保留地址失败；
5. PostgreSQL、Redis、S3/MinIO 和 Remote Backend 只通过声明的规则可达。

## Worker Drain 与滚动升级

Worker Deployment 使用 `maxUnavailable: 0`，默认
`terminationGracePeriodSeconds: 900`。进程收到 SIGTERM 后：

1. 调用绑定 Worker 身份的内部 Drain 接口；
2. 控制面停止发放新租约；
3. 当前批次继续续租并提交结果；
4. 当前 `run_once` 返回后进程退出。

优雅终止时间必须大于 Pipeline 中最长 Stage 的通常执行时间。超过期限被
Kubernetes 强制终止的 Stage 会在租约过期后按既有重试策略重新派发。

## 升级与回滚

升级前：

1. 备份 PostgreSQL 和对象存储；
2. 阅读迁移文件，确认迁移与旧版本控制面可并行运行；
3. 先在测试命名空间运行 Helm 模板、迁移和样本任务；
4. 确认新旧 Worker 的 Remote Backend 协议版本兼容。

应用回滚使用固定镜像 Tag：

```bash
helm history parser-serve -n parser-serve
helm rollback parser-serve <revision> -n parser-serve --wait --timeout 15m
```

Helm 回滚不会自动执行 Alembic downgrade。只有迁移明确支持且已备份时，才在
维护窗口手工执行 `alembic downgrade <revision>`；通常应保持向后兼容 Schema
并仅回滚应用镜像。

## 故障排查

```bash
kubectl -n parser-serve get pods -l app.kubernetes.io/instance=parser-serve
kubectl -n parser-serve logs job/parser-serve-parser-serve-migrate
kubectl -n parser-serve describe pod <worker-pod>
kubectl -n parser-serve get events --sort-by=.lastTimestamp
```

- 迁移 Job 失败：检查 `database-url`、网络策略和 PostgreSQL 锁；
- Worker 不注册：检查 Worker Key、Runtime/Vendor、探测命令和控制面地址；
- Worker 无租约：检查 Backend 版本、MIME、Runtime、标签、并发和内存保护；
- 加速卡不可见：检查 Node Selector、Device Plugin、资源名和容器运行时；
- 回调或 URL Source 失败：检查出口网络策略、DNS 和允许的目标地址。

Chart 当前提供生产配置骨架；在真实集群发布前仍需按组织要求配置 Ingress、
验证 NetworkPolicy、加强 Pod Security，并补齐证书、备份和告警策略。

Prometheus Operator 用户可启用 Chart 内置的带 API Key `ServiceMonitor` 和
基础 `PrometheusRule`；配置与告警处置说明见[可观测性](observability.md)。
