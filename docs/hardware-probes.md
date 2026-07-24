# Worker 硬件探测协议

Worker 注册使用统一的 `DeviceInfo`，心跳使用 `DeviceUsage`。控制面不解析任何
厂商命令输出，因此 CPU、NVIDIA 和国产加速卡不会把私有协议传播到调度层。

## 内置探测

- CPU：读取处理器型号、系统总内存、可用内存和一分钟负载。
- NVIDIA CUDA：使用 `nvidia-smi` 的无表头 CSV 查询模式，发现全部 GPU，并
  在每次心跳采集利用率、显存使用量、显存总量和温度。

CUDA Worker 镜像默认设置
`PARSER_WORKER_DEVICE_PROBE_REQUIRED=true`。`nvidia-smi` 缺失、超时或返回
非法数据时 Worker 不会使用虚假的 GPU 注册；运行期间探测失败会先发送
`unhealthy` 心跳，然后停止拉取新 Stage。

## 厂商探测命令

Ascend、MLU、DCU、MUSA、XPU 或定制平台通过
`PARSER_WORKER_DEVICE_PROBE_COMMAND` 接入适配脚本。该值按 Pydantic Settings
规则使用 JSON 数组，例如：

```bash
export PARSER_WORKER_DEVICE_PROBE_COMMAND='["/opt/parser/bin/ascend-probe","--json"]'
export PARSER_WORKER_DEVICE_PROBE_REQUIRED=true
```

Worker 直接以参数数组执行命令，不经过 shell。探测命令不得把凭证放进参数或
输出。超时、最大输出和失败策略分别由以下变量控制：

```text
PARSER_WORKER_DEVICE_PROBE_TIMEOUT_SECONDS=5
PARSER_WORKER_DEVICE_PROBE_MAXIMUM_OUTPUT_BYTES=1048576
PARSER_WORKER_DEVICE_PROBE_REQUIRED=true
```

命令标准输出必须是严格 JSON，不能包含日志或额外字段：

```json
{
  "schema_version": "1.0",
  "devices": [
    {
      "device_id": "ascend-0",
      "vendor": "huawei",
      "runtime": "ascend",
      "model": "Ascend 910B",
      "total_memory_bytes": 68719476736,
      "driver_version": "24.1",
      "runtime_version": "8.0"
    }
  ],
  "usage": [
    {
      "device_id": "ascend-0",
      "utilization_percent": 31.5,
      "memory_used_bytes": 8589934592,
      "memory_total_bytes": 68719476736,
      "temperature_celsius": 52.0
    }
  ]
}
```

约束：

- `schema_version` 当前为 `1.0`。
- `device_id` 在一个 Worker 内唯一且长期稳定。
- `usage.device_id` 必须引用同一响应中的设备，且不得重复。
- 所有设备的 `runtime` 和 `vendor` 必须与 Worker 镜像配置一致。
- 百分比、内存和温度范围由 `parser_serve/schema/hardware.py` 严格校验。
- 启动时的设备集合固定到本次 Worker 注册；心跳中出现的未知设备不会上报。

厂商适配脚本应只负责把稳定的厂商 API 或 CLI 输出翻译成这个协议。模型
Backend、任务租约和 Artifact 上传仍由通用 Worker Agent 负责。

## 静态降级

`device_probe_required=false` 时，探测工具不可用会退回
`PARSER_WORKER_DEVICE_*` 静态声明。这只适合开发和硬件 bring-up；生产加速卡
Worker 应启用 required 模式。注册标签 `parser_serve.hardware.probe` 会标明
`builtin`、`nvidia-smi`、`custom` 或 `configured`，便于管理接口识别数据来源。

## 系统工具健康

Worker 的 `resources.health_checks` 与设备使用率一起在每次心跳上报。CPU
Worker 对注册时实际启用的 LibreOffice 和 FFmpeg/ffprobe 执行持续可用性
复检；任一必需工具消失都会发送 `unhealthy` 状态和不包含本机路径的稳定错误
说明，然后停止拉取新 Stage。

LibreOffice 启动时不可用并不会禁用 DOCX/PPTX/XLSX 解析，而是从
`builtin_office` 的 Worker 能力中移除旧格式 MIME。Scheduler 对任务 MIME、
Worker 上报能力、Backend 版本和 Runtime 同时校验，因此 `.doc/.ppt/.xls`
不会被派发到无法转换的节点。管理 Web UI 会显示每项健康检查的正常或异常
状态。
