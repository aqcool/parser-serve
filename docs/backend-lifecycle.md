# Worker Backend 模型生命周期

本地模型 Backend 可以实现 `ManagedBackend` 生命周期：

```python
class LocalModelBackend:
    @property
    def capability(self) -> BackendCapability: ...

    async def load(self) -> None: ...

    async def unload(self) -> None: ...

    async def execute(self, context: BackendContext) -> BackendOutput: ...
```

`load()` 应完成模型权重、Tokenizer 和设备运行时资源初始化；`unload()` 应释放
显存、文件句柄、进程池等资源。远程 HTTP Backend 是无状态调用器，不实现该
生命周期，也不能配置为本地预加载目标。

## 启动配置

`PARSER_WORKER_PRELOAD_BACKENDS` 使用精确的 Backend 名称和版本：

```bash
export PARSER_WORKER_PRELOAD_BACKENDS='[
  {"name":"local_paddleocr","version":"1.0"},
  {"name":"local_vlm","version":"2.1"}
]'
```

Worker 在向控制面注册能力前按配置顺序加载模型。加载具有以下语义：

- 同一名称和版本只加载一次；
- 目标不存在或不支持生命周期时，Worker 启动失败且不会注册虚假能力；
- 一批加载中途失败时，逆序卸载本批已经加载成功的模型；
- Worker 完成 Drain 并等待当前 Stage 后，按加载逆序卸载全部模型；
- 单个模型卸载失败不阻止其他模型释放，并记录不包含配置密钥的结构化警告。

生命周期由 Worker 进程持有，不通过公网管理接口远程强制卸载正在执行任务的
模型。变更预加载集合应使用滚动更新：新 Worker 先加载并注册，旧 Worker
Drain 后释放资源。

## 多设备执行

控制面为每个租约同时返回 `runtime` 和准确的 `device_id`。Backend 从
`BackendContext.lease.device_id` 获取本次执行设备，并在进入厂商运行时前绑定
相应设备。

设备选择按以下顺序稳定排序：

1. 数据库中该设备当前 Leased/Running Stage 数量更少；
2. 心跳上报的设备利用率和显存占用更低；
3. `device_id` 字典序，用于完全同分时确定性决策。

达到显存保护阈值或不满足任务 `minimum_memory_bytes` 的设备不会获得新租约。
Stage 重试或租约失效时清除旧设备绑定，再根据最新心跳重新选择，因此故障
设备恢复后无需重启 Worker。`device_id` 持久化在活动 Stage 中，并通过
Stage/租约 Schema 对外提供。
