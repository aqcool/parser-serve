# 输入内容安全

Parser Serve 不信任文件名、上传 `Content-Type`、URL 响应 Header 或对象存储
元数据中的任何单一信息。接入和执行链路使用扩展名、声明 MIME 与内容签名联合
校验。

## 支持的签名

当前无额外原生依赖即可识别：

- PDF；
- OLE Compound Document（`.doc/.ppt/.xls`）；
- ZIP 容器（OOXML 与 EPUB）；
- JPEG、PNG、GIF、TIFF、BMP、WebP、AVIF、HEIF/HEIC；
- WAV、FLAC、AAC ADTS、MP3、Ogg/Opus、M4A；
- AVI、MP4/MOV、Matroska/WebM、MPEG Video；
- UTF-8/UTF-16 文本以及包含 HTML/XHTML 标记的网页。

校验结果使用严格的 `ContentInspection` Schema，包含规范 MIME、媒体类别、
容器类型、签名名称和文本标志。

## 校验位置

### HTTP 上传

控制面先读取最多 64 KiB 签名样本，同时优先执行上传大小限制。校验失败不会
创建 Storage 对象或数据库记录。`application/octet-stream` 只在扩展名与已知
二进制签名一致时接受，并规范化为实际 MIME。

### URL Source

Worker 在完成有界下载后检查响应 Content-Type、目标文件名和内容签名。失败时
删除临时文件。DNS、逐跳重定向和公网地址校验仍在签名校验之前执行。

### S3/MinIO Source

Worker 校验 Bucket allowlist、ContentLength、实际流长度，再根据任务中的
Source Metadata 和下载内容执行签名校验；失败时关闭 Body 并删除临时文件。

### 已上传文件传输

控制面返回数据库保存的 `Content-Length` 与 `X-Content-SHA256`。Worker 将
它们与租约中的 `size_bytes`、`sha256` 对比，并重新计算实际下载哈希。执行
Backend 前还会重复内容签名校验。

## 解析资源上限

CPU Worker 强制执行以下部署级上限：

| 环境变量 | 默认值 | 作用 |
| --- | ---: | --- |
| `PARSER_WORKER_MAXIMUM_PDF_PAGES` | `1000` | PDF 最大页数 |
| `PARSER_WORKER_MAXIMUM_IMAGE_PIXELS` | `100000000` | 图片宽高乘积上限 |
| `PARSER_WORKER_MAXIMUM_MEDIA_DURATION_SECONDS` | `14400` | 音视频最大时长 |
| `PARSER_WORKER_SUBPROCESS_MAXIMUM_MEMORY_BYTES` | `4294967296` | 系统工具进程最大虚拟内存 |
| `PARSER_WORKER_SUBPROCESS_MAXIMUM_CPU_SECONDS` | `900` | 系统工具累计 CPU 时间 |
| `PARSER_WORKER_SUBPROCESS_MAXIMUM_OUTPUT_FILE_BYTES` | `1073741824` | 系统工具可创建的单文件上限 |
| `PARSER_WORKER_SUBPROCESS_MAXIMUM_PROCESSES` | `64` | 系统工具及其子进程数上限 |

Pipeline 可用 `maximum_pages` 或 `maximum_pixels` 参数进一步收紧单个 Stage，
但超过 Worker 上限会在解析前失败。FFmpeg 的探测和音轨提取都会先读取媒体
时长；无法取得时长时拒绝继续，以免绕过上限。Stage 的
`timeout_seconds` 由 Worker 的 `asyncio.wait_for` 强制执行，续租不会延长
该执行期限。

LibreOffice、FFmpeg 和 ffprobe 命令还通过 Linux `prlimit` 设置地址空间、
累计 CPU 时间、输出文件和进程数限制，限制由子进程继承。CPU 生产镜像安装
`util-linux` 并设置
`PARSER_WORKER_SUBPROCESS_RESOURCE_LIMITS_REQUIRED=true`，缺少 `prlimit`
时会关闭失败而不是无隔离执行。默认裸机开发配置允许在不支持 `prlimit` 的
平台降级，仅适合本地测试；Helm 部署同样默认强制启用。Pod 的 CPU、内存和
临时盘资源仍是外层最终防线，二者不能互相替代。

## 已知边界

签名识别只证明格式族一致，不代表文件安全或语义有效。例如 ZIP Header 不能
单独证明 OOXML 内部结构完整。内置 Office Backend 还会限制 Archive 条目数、
累计解压大小、单文件大小、XML 大小和压缩比，并校验所需 OOXML 路径。

生产环境仍应继续配置：

- Worker 临时目录配额和更细粒度的容器隔离；
- 远程模型服务内部的页数、像素、帧数和推理资源二次上限；
- 杀毒或内容净化服务；
- 压缩容器递归层数限制；
- 按实际命名空间和依赖地址启用并验证 Helm 出口网络策略；
- 恶意、截断和解析器历史漏洞样本回归集。
