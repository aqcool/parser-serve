# Callback 接入与幂等

Task 可以配置 Callback URL、订阅事件和可选 HMAC Secret。Callback 是至少一次
投递：网络超时、接收方 `5xx`、认领超时接管或人工重发都可能让同一个事件到达
多次。接收方必须使用 `X-Parser-Event-ID` 或 JSON 中相同的 `event_id` 做
幂等去重，不能把 HTTP 请求次数当成业务发生次数。

## 请求

```http
POST /callback HTTP/1.1
Content-Type: application/json
User-Agent: parser-serve-callback/1.0
X-Parser-Event-ID: event_xxx
X-Parser-Timestamp: 1784865600
X-Parser-Signature: v1=<hex-hmac-sha256>
```

请求体是严格类型的 `CallbackEvent`。同一 `event_id` 的重试和人工重发保持
相同事件语义；接收时间和 HTTP 投递次数可能不同。

配置 Secret 后，签名原文为：

```text
ASCII(X-Parser-Timestamp) + "." + 原始请求体字节
```

使用 Secret 对原文计算 HMAC-SHA256，并与 `X-Parser-Signature` 中 `v1=`
后的十六进制摘要做常量时间比较。必须先验证签名，再解析和处理业务内容。
接收方还应限制时间戳与当前时间的偏差，例如五分钟，以降低已捕获请求的重放
窗口；时间戳校验不能代替 Event ID 幂等。

## 推荐接收流程

在一个数据库事务中执行：

1. 验证时间戳、HMAC 和请求体 Schema；
2. 尝试插入以 `event_id` 为唯一键的接收记录；
3. 唯一键已存在时不重复执行副作用，直接返回 `2xx`；
4. 新事件执行业务更新并提交；
5. 只有在确认需要 Parser Serve 重试时才返回非 `2xx`。

如果业务处理耗时较长，应先原子持久化事件再返回 `2xx`，由接收方自己的队列
异步处理。不要在副作用完成后返回 `5xx`，否则会产生一次必然的重复投递。

## 服务端重试语义

- 任意 `2xx` 表示投递成功；
- 网络错误、超时和非 `2xx` 响应记录为失败，并按配置进行指数退避；
- 服务端不跟随重定向，避免目标跳转到私网；
- 每次尝试都有不可变审计记录，达到最大次数后进入失败终态；
- 管理 API 可以人工重发，但不会生成新的业务 `event_id`。

服务端会限制连接时间和响应摘要大小。接收方应尽快返回简短响应；响应内容不
作为协议数据使用。

## 安全边界

Callback URL 在保存和每次投递前都会执行协议、凭证、DNS 和目标 IP 检查，
拒绝 loopback、link-local、私网和其他非公网地址，也不跟随 HTTP 重定向。
生产 Kubernetes 部署还应启用
[出口 NetworkPolicy](kubernetes.md#网络策略与内部-worker-api)，作为 DNS
重绑定的第二层防护。

仓库端到端测试会启动真实本地 TCP 接收方，让 Dispatcher 对同一事件完成首次
投递和人工重发，并验证两次 HMAC 均有效、接收方只应用一次 Event ID。
