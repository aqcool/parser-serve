# Storage 配置

Parser Serve 的上传文件、Stage 中间产物和最终 `ParseResult` 共用 `Storage`
接口。单机开发可使用本地文件系统，多控制面和多 Worker 部署必须使用共享
S3/MinIO。

## 本地文件系统

```bash
PARSER_SERVE_STORAGE_BACKEND=local
PARSER_SERVE_LOCAL_STORAGE_PATH=./data/storage
```

本地实现使用同目录临时文件、`fsync` 和原子替换，拒绝绝对路径、反斜杠和
路径穿越。它不适合多个控制面副本。

## S3 或 MinIO

```bash
PARSER_SERVE_STORAGE_BACKEND=s3
PARSER_SERVE_S3_STORAGE_BUCKET=parser-data
PARSER_SERVE_S3_STORAGE_PREFIX=production/parser-serve
PARSER_SERVE_S3_STORAGE_REGION_NAME=cn-north-1
```

MinIO 额外设置：

```bash
PARSER_SERVE_S3_STORAGE_ENDPOINT_URL=http://minio:9000
AWS_ACCESS_KEY_ID=replace-me
AWS_SECRET_ACCESS_KEY=replace-me
```

认证沿用 boto3 标准 Credential Provider Chain，可使用环境变量、容器
Secret、实例角色或 Workload Identity。Parser Serve Settings 不接收也不回显
S3 Secret。

写入流程会：

1. 流式接收并同步计算大小与 SHA-256。
2. 超过接口配置的大小上限时在上传前失败。
3. 将完整临时对象通过 boto3 transfer manager 上传；S3 对象仅在成功提交后
   可见，失败不会暴露部分内容。
4. 在对象 metadata 写入 `parser-serve-sha256`。
5. 无论成功或失败都清理本地临时文件。

读取通过 `get_object` Body 分块返回并确保关闭连接。`NoSuchKey`/404 转为统一
不存在错误；鉴权、网络和服务端故障不会被伪装成不存在。

`GET /ready` 会对配置的 Storage 执行无写入的存在性检查。不存在的健康检查
Key 仍表示连接正常；权限、网络或服务端错误会使 `storage` 组件显示不健康。

普通 API Key 可以调用：

```text
GET /api/v1/tasks/{task_id}/artifacts/{artifact_id}/download-url
```

S3/MinIO 返回类型化的短期 `GET` URL 和准确过期时间。有效期由
`PARSER_SERVE_ARTIFACT_DOWNLOAD_URL_EXPIRES_SECONDS` 控制，默认 300 秒，范围
1–86400 秒。本地 Storage 返回 `409 CONFLICT`，调用方继续使用带 API Key 的
`.../content` 流式下载接口。
