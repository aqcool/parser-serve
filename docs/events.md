# 事件总线与实时流

Parser Serve 使用事务型数据库 Outbox 作为事件事实来源。业务代码不直接构造
数据库 `EventRecord`，而是通过 `TransactionalEventPublisher` 发布
`EventPayload` 判别联合类型。

## 发布边界

`DatabaseEventBus.publish()` 接收调用方现有的 SQLAlchemy Session，因此事件
和对应业务状态共享同一事务：

- Task 创建、取消和重试；
- Task 路由及 Stage DAG 创建；
- Stage 租约、运行、进度和完成；
- Worker 状态变化；
- Callback Delivery 状态变化；
- HTTP 与 MCP 提交产生的相同 Task 事件。

事务提交后状态和事件同时可见；回滚时两者同时消失。Event Bus 从强类型
Payload 推导 `event_type`、`task_id` 和 `worker_id`，避免生产者重复拼装索引
字段并产生不一致。

## 消费边界

`EventConsumer.consume()` 提供以下稳定过滤条件：

- Event 类型列表；
- `task_id`；
- `worker_id`；
- `last_event_id` 游标；
- 有界批量大小。

普通 JSON 查询、全局 SSE 和单 Task SSE 共享该接口。SSE 固定按
`occurred_at + event_id` 升序消费，因此同一时间戳的事件仍能稳定续传；
JSON 历史查询还可显式选择发生时间或事件类型及排序方向。

Callback Dispatcher 是一个具有额外认领语义的 Outbox 消费者。它使用行锁和
`callback_processed` 保证同一内部事件只物化一次投递；数据保留服务不会在
回调物化前删除相关 Task 事件。

## 扩展原则

数据库始终是事件恢复和审计的权威来源。后续接入 Kafka、NATS 或其他消息
系统时，应作为提交后的异步转发消费者：

```text
业务事务 -> Database Event Bus -> 提交
                              -> Relay Consumer -> 外部 Broker
```

不得在业务事务中同时写数据库和外部 Broker，也不能让 Broker 消息替代
数据库事件 ID、回调幂等或 SSE `Last-Event-ID`。外部转发必须接受重复消息，
并以 `event_id` 幂等。

## 对外接口

```text
GET /api/v1/events
GET /api/v1/tasks/{task_id}/events
GET /api/v1/events/stream
GET /api/v1/tasks/{task_id}/events/stream
```

所有接口使用普通 API Key。SSE 使用 `Last-Event-ID` Header；游标已过期或
不存在时返回 404，调用方应重新读取当前 Task 快照，而不是猜测丢失事件。

服务端不为每个 SSE 连接维护无界内存队列，并限制单个帧的发送阻塞时间。
`PARSER_SERVE_SSE_MAXIMUM_SEND_DELAY_SECONDS` 默认为 30 秒；客户端持续慢于
该阈值时连接会被主动结束。客户端应使用最后成功收到的 Event ID 重连，数据库
事件游标会继续提供至少一次投递语义。
