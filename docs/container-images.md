# 容器镜像说明

## 1. 当前镜像边界

仓库中的镜像定义按进程职责和硬件运行时分离：

| 镜像 | Dockerfile | Python Profile |
| --- | --- | --- |
| 控制面 | `docker/control-plane.Dockerfile` | `control-plane` |
| Web UI | `docker/web.Dockerfile` | 不适用 |
| CPU Worker | `docker/worker-cpu.Dockerfile` | `worker-cpu` |
| NVIDIA CUDA Worker | `docker/worker-cuda.Dockerfile` | `worker-cuda` |
| Ascend Worker | `docker/worker-ascend.Dockerfile` | `worker-ascend` |
| MLU Worker | `docker/worker-mlu.Dockerfile` | `worker-mlu` |
| DCU Worker | `docker/worker-dcu.Dockerfile` | `worker-dcu` |
| MUSA Worker | `docker/worker-musa.Dockerfile` | `worker-musa` |
| XPU Worker | `docker/worker-xpu.Dockerfile` | `worker-xpu` |

根目录 `dockerfile` 暂时保留为 CPU Worker 的兼容构建入口，规范入口是
`docker/worker-cpu.Dockerfile`。

控制面不包含 LibreOffice、FFmpeg 或任何硬件推理运行时。CPU Worker
安装 LibreOffice Writer、Impress、Calc、FFmpeg、ffprobe 和中文字体。
LibreOffice 只执行 `.doc → .docx`、`.ppt → .pptx`、`.xls → .xlsx`
预处理转换，不注册为解析 Backend。CPU Worker 还安装 `util-linux`，并强制
使用 `prlimit` 限制这些系统工具及其子进程；限制项见
[输入内容安全](input-security.md#解析资源上限)。

## 2. 厂商基础镜像

CUDA 和国产硬件 Dockerfile 不提供默认厂商基础镜像，构建时必须显式传入
经过验证的基础镜像：

```bash
docker build \
  --build-arg CUDA_BASE_IMAGE=<经过验证的 CUDA Python 基础镜像> \
  -f docker/worker-cuda.Dockerfile .
```

其他构建参数分别为：

| Runtime | 构建参数 |
| --- | --- |
| Ascend | `ASCEND_BASE_IMAGE` |
| MLU | `MLU_BASE_IMAGE` |
| DCU | `DCU_BASE_IMAGE` |
| MUSA | `MUSA_BASE_IMAGE` |
| XPU | `XPU_BASE_IMAGE` |

基础镜像必须包含与设备驱动匹配的厂商运行时以及 Python 3.12 或 3.13。
国产硬件镜像直接继承各自厂商基础镜像，禁止继承 CUDA 镜像。实际版本需在
拥有对应设备后建立驱动、固件、运行时和推理框架兼容矩阵。

本阶段只提交镜像定义，没有拉取基础镜像，也没有执行 Docker 构建。

本地多服务编排见 [Docker Compose 本地部署](local-compose.md)。默认只启用
CPU Worker；CUDA 和国产硬件 Worker 使用独立 Profile，且仍构建各自的
Dockerfile，不会合并硬件运行时。

## 3. Worker 设备声明

统一入口 `parser-worker` 读取带 `PARSER_WORKER_` 前缀的配置：

| 环境变量 | 含义 |
| --- | --- |
| `PARSER_WORKER_CONTROL_PLANE_URL` | 控制面地址 |
| `PARSER_WORKER_API_KEY` | Worker 专用 API Key |
| `PARSER_WORKER_WORKER_ID` | 全局唯一 Worker ID |
| `PARSER_WORKER_DEVICE_RUNTIME` | `cpu/cuda/ascend/mlu/dcu/musa/xpu` |
| `PARSER_WORKER_DEVICE_VENDOR` | 与 Runtime 匹配的厂商 |
| `PARSER_WORKER_DEVICE_ID` | 设备 ID |
| `PARSER_WORKER_DEVICE_MODEL` | 设备型号 |
| `PARSER_WORKER_DEVICE_TOTAL_MEMORY_BYTES` | 可选，总内存或显存 |
| `PARSER_WORKER_DEVICE_DRIVER_VERSION` | 可选，驱动版本 |
| `PARSER_WORKER_DEVICE_RUNTIME_VERSION` | 可选，运行时版本 |
| `PARSER_WORKER_PRELOAD_BACKENDS` | 本地 Managed Backend 名称与版本 JSON 数组 |

Schema 会拒绝 Runtime 与 Vendor 不匹配的配置。当前厂商镜像中的设备信息是
显式声明值，真实设备自动探测仍需按平台实现。

硬件联调时允许 Worker 以零 Backend 能力注册。此时控制面可以展示 Worker
和设备状态，但调度器不会向它派发解析 Stage，避免把尚未接入的模型能力
误报为可用。安装厂商 SDK 并实现对应 Backend 后，只有真实注册的能力才会
参与路由和任务派发。

## 4. Web 镜像

Web UI 使用 Vue 3、TypeScript、Vite 和 shadcn-vue。当前尚未生成并提交
`package-lock.json`，因此 Dockerfile 暂时使用 `npm install`。发布前必须
在允许安装依赖的环境中生成锁文件，将构建步骤切换为 `npm ci`，再完成
TypeScript、生产构建和 Nginx SPA 路由验证。

## 5. 发布前验证

镜像定义的静态测试只检查职责隔离、Profile、Runtime、厂商基础镜像参数和
CPU 系统工具声明。发布前仍必须在目标环境完成：

1. 基础镜像来源和摘要锁定。
2. `uv sync --frozen --no-dev` 安装验证。
3. LibreOffice、FFmpeg 和 ffprobe 容器内执行测试。
4. 厂商设备、驱动、内存和利用率真实探测。
5. 对应 Backend 导入、健康检查和端到端解析。
6. 非 root 用户的设备权限、临时目录和模型缓存挂载验证。
7. 镜像漏洞扫描、SBOM、签名和发布。
