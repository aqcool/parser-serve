# 任务队列与多机派发

Parser Serve 使用“数据库权威租约 + 可选 Redis Streams 唤醒”的多机派发
模型。Worker 不需要暴露入站端口，只通过内部 HTTP API 注册、心跳、拉取、
续租和提交结果。

Worker 收到 SIGTERM 后先调用绑定自身 Worker API Key 的
`POST /internal/v1/workers/{worker_id}/drain`。控制面立即停止向它发放新租约，
Worker 等待当前批次的 Stage 执行、续租和结果提交结束后退出。Drain 通知失败
时仍停止拉取，控制面最终通过心跳超时将其判定离线。

## Worker 选择

Worker 仍以 Pull 模式请求租约，但控制面不会简单地把 Stage 交给最先轮询的
任意兼容节点。每次租约请求都会对在线兼容 Worker 执行准入排序：

- Backend 名称与版本、Runtime、任务 Worker 标签必须匹配；
- 满足任务最小可用设备内存，且仍有最大并发槽位；
- 心跳上报的设备显存/内存利用率达到
  `PARSER_SERVE_SCHEDULER_MAXIMUM_DEVICE_MEMORY_UTILIZATION_PERCENT`
  （默认 95%）时，该设备暂时退出新租约候选；
- `prefer` 请求先按声明的 Runtime 顺序选择硬件；首选 Runtime 无可用节点时
  才进入后续 Runtime（通常为 CPU）；
- `scheduling_weight` 越高，基础优先级越高；
- 数据库中的 Leased/Running Stage 数量作为权威并发负载；
- 心跳中的 CPU 利用率、设备利用率、设备内存压力和上报任务数用于动态降权。

选定 Worker 和 Runtime 后，Scheduler 还会为租约绑定准确的 `device_id`。
同一 Worker 有多张兼容加速卡时，先选择活动租约更少的设备，再比较实时利用率
和显存压力，最后用设备 ID 稳定决策。一个轮询批次内的新租约会立即计入设备
占用，避免同批任务全部落到同一张空闲卡。Backend 通过
`BackendContext.lease.device_id` 绑定厂商运行时。详见
[Worker Backend 模型生命周期](backend-lifecycle.md)。

Runtime 偏好是第一层排序，首选 Runtime 的低权重节点不会被降级 Runtime 的
高权重节点越过。相同 Runtime 层级内的综合分数为“配置权重 × 剩余负载
因子”，负载因子最低保留 5%，避免高权重节点因瞬时满载产生数值异常。同分
时优先活动租约更少的节点，最后按 `worker_id` 稳定决策。高优先级节点不可用
或达到最大并发后，其他兼容节点自动获得资格。

内存保护只阻止新租约，不中断正在执行的 Stage。利用率恢复到阈值以下后，
Worker 无需重新注册即可再次参与调度；未上报内存数据的设备仍通过并发限制、
任务声明的 `minimum_memory_bytes` 和 Worker 自身模型运行时保护约束。

普通 API Key 可以通过
`PATCH /api/v1/management/workers/{worker_id}` 调整
`scheduling_weight`（1–1000）和 `maximum_concurrency`。Web UI 的 Worker
管理页提供同一配置入口。

## 一致性边界

- PostgreSQL/数据库保存 Task、Stage、Worker、租约所有权和幂等结果。
- Scheduler 使用事务、行锁和 `SKIP LOCKED` 保证同一 Stage 不会同时发给
  两个正常 Claim。
- Redis Streams 只发布 Stage 可能可用的通知，不保存权威任务状态。
- 通知允许重复、延迟或丢失；Worker 被唤醒后必须重新查询数据库并竞争租约。
- Redis 不可用时，任务创建和 Stage 完成仍然成功，Worker 退化为数据库轮询。

这种边界避免数据库与 Redis 之间产生无法原子提交的“双状态任务”。租约超时、
续租、重排和完成校验不会依赖某条 Redis 消息是否仍然存在。

## 长轮询流程

```text
Worker               Control Plane             Redis             Database
  | lease(wait=20s)       |                       |                   |
  |---------------------->| snapshot cursor       |                   |
  |                       |---------------------->|                   |
  |                       | try lease -------------------------------->|
  |                       |<-------------------------- no Stage -------|
  |                       | XREAD after cursor    |                   |
  |                       |---------------------->|                   |
  |                       |<------ notification --|                   |
  |                       | try lease -------------------------------->|
  |<----------------------| leased Stage + token                      |
```

先取 Stream 游标再查数据库，避免 Stage 恰好在第一次数据库查询与等待之间发布
而造成无谓的完整等待。无论 `XREAD` 是因消息还是超时返回，控制面都会再查询
一次数据库。

## 通知来源

以下状态变化会发送严格类型的 `StageQueueNotice`：

- Task 自动或人工路由完成；
- 失败或取消 Task 被人工重试；
- Stage 完成，可能解锁 DAG 下游 Stage；
- 过期租约被协调器重排。

通知发布发生在数据库提交之后。发布失败只记录不含连接详情的警告，不回滚已经
提交的业务状态。

## 控制面配置

默认不要求 Redis：

```text
PARSER_SERVE_TASK_QUEUE_BACKEND=database
```

多控制面生产部署：

```text
PARSER_SERVE_TASK_QUEUE_BACKEND=redis_streams
PARSER_SERVE_REDIS_URL=redis://redis:6379/0
PARSER_SERVE_REDIS_STAGE_STREAM_KEY=parser-serve:stage-availability
PARSER_SERVE_REDIS_STAGE_STREAM_MAXIMUM_LENGTH=10000
PARSER_SERVE_WORKER_LEASE_WAIT_MAXIMUM_SECONDS=30
```

Stream 使用近似 `MAXLEN` 限制长度。通知不使用 Consumer Group，因为每个控制面
副本都需要收到唤醒信号；真正的单消费者竞争发生在数据库行锁中。

## Worker 配置

```text
PARSER_WORKER_LEASE_WAIT_SECONDS=20
PARSER_WORKER_POLL_INTERVAL_SECONDS=1
PARSER_WORKER_REQUEST_TIMEOUT_SECONDS=60
PARSER_WORKER_PRELOAD_BACKENDS='[{"name":"local_model","version":"1.0"}]'
```

`lease_wait_seconds` 范围为 `0..30`，且 HTTP 请求超时必须大于长轮询时间。
设置为 `0` 可关闭长轮询。

## 健康与降级

`GET /ready` 分别检查 Storage、数据库（已配置时）和任务队列。Redis 模式下
队列检查使用 `PING`；响应只包含异常类型，不泄露带密码的 Redis URL 或底层
连接详情。

Readiness 失败用于阻止负载均衡继续向故障副本分配新请求，但任务队列通知失败
本身不会破坏数据库中已有任务。运维系统应对持续的 `task_queue` 不健康告警，
同时观察 Worker 空轮询延迟。
