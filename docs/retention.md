# 数据保留与清理

Parser Serve 对上传文件、解析 Artifact 和持久化事件执行分批保留清理。
对象内容与数据库元数据由同一控制面流程协调处理，数据库仍是清理状态的
权威来源。

## 默认策略

| 资源 | 默认保留时间 | 保护规则 |
| --- | ---: | --- |
| 上传文件 | 1 天 | 被 Pending、Leased 或 Running Task 引用时跳过 |
| Artifact | 30 天 | 所属 Task 为 Pending、Leased 或 Running 时跳过 |
| 事件 | 7 天 | 尚未物化回调投递的回调源事件跳过 |

新上传文件和新 Artifact 会写入显式 `expires_at`。升级前没有过期时间的
记录按 `created_at + 当前部署保留时间` 判断。事件使用 `occurred_at`
判断；`task.created`、`task.status_changed` 和 `task.progress_updated`
只有在完成回调物化后才能删除。

## 配置

以下环境变量由控制面读取：

```dotenv
PARSER_SERVE_UPLOADED_FILE_RETENTION_SECONDS=86400
PARSER_SERVE_ARTIFACT_RETENTION_SECONDS=2592000
PARSER_SERVE_EVENT_RETENTION_SECONDS=604800
PARSER_SERVE_RETENTION_CLEANUP_ENABLED=true
PARSER_SERVE_RETENTION_CLEANUP_INTERVAL_SECONDS=300
PARSER_SERVE_RETENTION_CLEANUP_BATCH_SIZE=500
```

保留时间是部署级配置，不属于 Web UI 动态设置。将
`PARSER_SERVE_RETENTION_CLEANUP_ENABLED=false` 可关闭后台循环，但仍可
通过管理接口手动执行。后台和手动操作都使用数据库行锁；PostgreSQL 上通过
`SKIP LOCKED` 避免多个控制面副本重复处理同一批记录。

## 管理接口

普通 API Key 可以先试运行：

```bash
curl -X POST \
  http://localhost:8000/api/v1/management/maintenance/retention/run \
  -H "Authorization: Bearer ${PARSER_SERVE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"dry_run":true,"maximum_records":500}'
```

确认统计后，把 `dry_run` 改为 `false` 执行。`maximum_records` 的范围是
1–10000，并分别限制每一种资源在单轮查询中的记录数。响应返回选中数量、
因活跃任务跳过的数量以及存储删除失败数量。Web UI 的“系统信息”页也提供
“试运行”和带确认提示的“执行清理”操作。

## 失败与一致性

清理先删除对象内容，再删除数据库记录。对象存储删除失败时，该条数据库
记录保持不变，后续清理轮次可以重试。Artifact 删除成功后，会同步清除
Task 和 Stage 中指向同一 `storage_uri` 的结果引用。数据库提交失败可能导致
对象已经删除而元数据暂时仍在；下一轮删除必须依赖 Storage 的幂等删除语义。

执行前应保证 Storage 实现的 `delete` 对不存在对象返回成功。生产环境还应
对 `storage_delete_failures` 和清理日志设置告警，并根据业务恢复要求配置
对象存储版本控制或外部备份。
