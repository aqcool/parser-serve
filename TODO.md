# Parser Serve TODO

总体方案见 [docs/architecture-plan.md](docs/architecture-plan.md)。

## 使用规则

- `[ ]`：尚未开始
- `[x]`：已完成并通过测试
- 部分完成的事项保持 `[ ]`，并在描述中注明当前进度。
- 每项完成时应同时补充测试和文档。
- 发生架构调整时，先更新总体方案，再调整本清单。

## P0：项目基础

- [x] 初始化 Python 项目
- [x] 建立 FastAPI、Pydantic Settings 和 Ray Serve 基础依赖
- [x] 将核心、控制面、接入协议和各硬件 Worker 拆分为独立依赖 Profile
- [x] 编写依赖 Profile、系统依赖边界和镜像安装说明
- [x] 建立 `parser_serve/schema/` 目录
- [x] 建立 `api`、`domain`、`persistence`、`control`、`backends`、`worker` 等职责目录（Pipeline 定义归属 `schema`，路由与默认目录归属 `control`）
- [x] 配置 Ruff 格式化/Lint 和 Pyright 严格类型检查
- [x] 配置 Pytest、Unittest 兼容测试发现和 80% 覆盖率门槛
- [x] 配置 OpenAPI Schema 与提交快照校验
- [x] 配置 Python 3.12/3.13 CI
- [x] 确定应用版本、API 版本和结果 Schema 版本策略
- [x] 建立 FastAPI 应用工厂、健康检查和就绪检查

## P0：Schema

- [x] 实现严格 Pydantic 基类，禁止未知字段
- [x] 实现 `JsonValue` 和通用 ID 类型
- [x] 实现统一成功、列表和错误响应
- [x] 实现稳定的错误码枚举
- [x] 实现 Source 联合类型
- [x] 实现 Task 和 Stage 类型
- [x] 实现 Event 类型
- [x] 实现 Artifact 类型
- [x] 实现统一 ParseResult 和 Block 联合类型
- [x] 实现 Pipeline 类型
- [x] 实现 Backend Capability 类型
- [x] 实现 Hardware、Device 和 Worker 类型
- [x] 实现 Callback 类型
- [x] 实现 Dashboard 类型
- [x] 实现 API Key 类型
- [x] 实现当前已规划接口的 Query 参数类型
- [x] 为 Schema 增加字段描述、范围和示例
- [x] 增加 JSON 序列化往返测试
- [x] 增加 OpenAPI 快照测试
- [x] 检查 OpenAPI 中不存在无约束 `object` 或 `Any`

## P0：API Key

- [x] 定义 API Key 数据库模型
- [x] 实现安全 Key 生成
- [x] 仅存储 Key 哈希和前缀
- [x] 实现 `Authorization: Bearer` 验证
- [x] 兼容 `X-API-Key`
- [x] 实现创建、查询、禁用、启用、轮换和删除接口
- [x] 防止删除或禁用最后一个有效普通 API Key
- [x] 实现独立且绑定 `worker_id` 的 Worker API Key
- [x] 对设置对象和认证错误中的 Key、Secret 脱敏
- [x] 增加鉴权失败、Key 过期和禁用测试

## P0：持久化与基础设施

- [ ] 接入 PostgreSQL（Compose、asyncpg、Alembic、Helm 和 PostgreSQL 17 CI/SKIP LOCKED 集成测试已配置，等待 CI 实际运行确认）
- [x] 选择并配置 Alembic 数据库迁移工具
- [x] 建立首个控制面数据库迁移并验证升级、回滚和模型一致性
- [x] 定义 Task、Stage、Event、Worker、Pipeline 和 Backend 表
- [x] 定义 API Key、Artifact 和 Callback Delivery 表
- [x] 实现异步 SQLAlchemy Engine 和 Session 生命周期封装
- [x] 接入 Redis Streams Stage 可用性通知
- [x] 实现任务队列抽象，并保留无外部依赖的数据库轮询实现
- [x] 实现事务型事件发布和游标消费抽象，并让 HTTP、MCP、调度、回调复用
- [x] 明确并实现数据库权威租约和续租；Redis 仅负责跨控制面唤醒，故障时降级轮询
- [x] 定义流式 Storage 接口
- [x] 实现带原子写入、大小限制、SHA-256 和路径穿越防护的本地文件存储
- [x] 实现带流式限制、SHA-256、路径校验和错误映射的 S3/MinIO 共享存储
- [x] 实现上传文件、Artifact 生命周期和过期清理
- [x] 为 Storage、数据库和任务队列增加就绪健康检查

## P0：任务与 Pipeline

- [x] 实现 Task 状态机
- [x] 实现 Stage 状态机
- [x] 实现取消、失败和重试规则（包含 HTTP 手动取消、任务重试、Worker 自动失败、指数退避和租约超时重派）
- [x] 实现至少一次执行和幂等结果写入（Task 提交、Artifact 上传和 Stage 完成均支持幂等重放与冲突检测）
- [x] 实现任务提交 `Idempotency-Key` 及请求冲突检测
- [x] 实现 Pipeline DAG 定义
- [x] 实现 DAG 循环和依赖校验
- [x] 实现 Pipeline 版本管理
- [x] 保证可执行任务绑定具体 Pipeline 版本
- [x] 实现 Pipeline Router
- [x] 实现任务创建时的原子即时路由和失败保存点回滚
- [x] 实现 Pending 无 Stage 任务的后台批量重试路由
- [x] 实现 Backend Registry
- [x] 实现 Backend 优先级和 fallback
- [x] 实现 Stage 进度聚合为 Task 进度

## P0：Worker 与多机调度

- [x] 实现 Worker 注册
- [x] 实现带单调序列号的 Worker 心跳
- [x] 实现统一硬件设备探测接口、严格快照 Schema、CPU/NVIDIA 内置探测和国产运行时厂商命令适配入口
- [x] 实现 Backend 能力上报
- [x] 实现配置驱动的统一远程 Backend 1.0 协议和 Worker 注册
- [x] 为 PaddleOCR、PaddleOCR-VL、HunyuanOCR、MinerU、ASR、VLM 和视频 VLM 增加类型化远程引擎预设
- [x] 实现远程 Backend Bearer/X-API-Key 认证、流式上传、超时和响应大小限制
- [x] 实现远程 ParseResult 归属校验、错误重试映射和辅助 Artifact 限制
- [x] 实现 Worker 主动拉取 Stage
- [x] 实现带安全令牌的 Stage 租约
- [x] 实现长任务续租
- [x] 实现租约过期后的重试、重派和最终失败
- [x] 实现 Worker 最大并发控制
- [x] 实现 Worker 调度权重，并开放 API 与 Web 管理
- [x] 实现 Worker 标签与任务标签约束
- [x] 实现 `draining` 优雅停止接收新租约
- [x] 实现心跳超时离线判定
- [x] 实现按 Backend、Runtime、标签、设备内存、权威活动租约及动态利用率调度
- [x] 实现 `auto`、`prefer` 和 `require` 硬件策略
- [x] 实现 Worker 在有效 Stage 租约内幂等上传 Artifact
- [x] 增加租约过期、令牌错误、重试耗尽和重复心跳测试

## P0：CPU Worker

- [x] 实现 LibreOffice `.doc → .docx`、`.ppt → .pptx`、`.xls → .xlsx` 无界面转换工具
- [x] 完成 LibreOffice 格式映射和异常单元测试
- [ ] 使用真实 `.doc`、`.ppt`、`.xls` 样本完成本机和容器端到端测试
- [ ] 完成 LibreOffice 和 FFmpeg Worker 镜像构建验证（当前 Dockerfile 已声明依赖）
- [x] 在 Worker 文档预处理链路中调用 LibreOffice 工具处理 `.doc`、`.ppt` 和 `.xls`（LibreOffice 不注册为 Backend）
- [x] 实现 FFmpeg Backend 的媒体探测和音轨标准化操作
- [x] 实现严格类型的 ffprobe 元数据提取
- [x] 实现文本和 Markdown Backend
- [x] 实现 DOCX 段落与表格 Backend
- [x] 实现 PPTX 幻灯片文本与定位 Backend
- [x] 实现 XLSX 工作表、共享字符串和单元格表格 Backend
- [x] 为 Office Open XML 增加条目数、解压大小、压缩比、路径和 XML 安全限制
- [x] 实现带页数限制的基础 PDF 文本 Backend
- [x] 实现静态 HTML 正文、标题和链接提取 Backend
- [x] 实现带像素限制的图片/照片元数据和 EXIF Backend
- [x] 实现 CPU Worker 健康检查、LibreOffice/FFmpeg 运行中复检和类型化故障上报
- [x] 建立 `parser-worker-cpu` 独立 Dockerfile（镜像构建和容器端到端验证待完成）
- [ ] 验证 `.doc/.ppt/.xls` 旧格式升级的容器内转换
- [ ] 验证 FFmpeg 和 ffprobe 容器内执行
- [ ] 增加中文字体渲染测试

## P1：业务 API

- [x] 实现流式文件上传、元数据查询和受鉴权的内容下载
- [x] 实现 URL、S3/MinIO 对象存储、上传文件和文本 Source
- [x] 实现创建解析任务
- [x] 实现查询任务
- [x] 实现查询 Stage 和事件
- [x] 实现取消任务
- [x] 实现重试任务
- [x] 实现经过 Schema 校验的结果查询和原始结果流式下载
- [x] 实现 Artifact 列表、API Key 鉴权下载和 S3/MinIO 短期签名下载地址
- [x] 实现全部列表接口的稳定游标分页
- [x] 实现全部列表接口的强类型过滤、稳定排序字段和排序方向
- [x] 实现 `X-Request-ID`
- [x] 为当前健康检查、能力和系统信息路由定义稳定 `operation_id`
- [x] 为当前健康检查、能力和系统信息路由声明成功和错误响应模型
- [x] 为所有当前路由定义唯一稳定的 `operation_id`
- [x] 为所有当前路由声明成功和统一错误响应模型
- [x] 补充 OpenAPI 描述和示例

## P1：开放管理 API

- [x] 复用开放 Task 查询、过滤、取消、重试和管理路由接口实现任务管理
- [x] 实现 Worker 查询和管理接口
- [x] 实现 Worker Drain、心跳状态和离线协调接口
- [x] 实现 Backend 创建、查询和配置接口
- [x] 实现 Pipeline 创建、列表、校验、真实测试、发布和历史版本回滚接口
- [x] 实现回调投递查询和重发接口
- [x] 实现持久化动态系统设置查询和批量更新接口
- [x] 让上传、Artifact、HTTP/MCP 结果限制和回调尝试次数读取动态设置
- [x] 实现基于已发布 Pipeline、启用 Backend 和在线 Worker 的系统能力查询接口
- [x] 通过系统能力接口提供在线硬件 Runtime、厂商、Worker 和设备数量
- [x] 实现支持时间窗口、Pipeline、Backend、Worker、Runtime 和媒体过滤的 Dashboard 聚合接口
- [x] 确保全部已实现管理接口可以通过普通 API Key 对外调用
- [x] 为外部集成补充鉴权、任务、分页、结果和管理 API 示例

## P1：回调

- [x] 定义回调事件 Schema
- [x] 实现任务创建、运行、成功、失败、取消和进度事件
- [x] 实现 HMAC-SHA256 签名
- [x] 实现事件 ID 和时间戳
- [x] 实现回调超时
- [x] 实现指数退避重试
- [x] 实现最大重试次数和失败终态
- [x] 保存回调投递记录
- [x] 保存每一次尝试的独立响应历史，区分生命周期序号和本轮尝试号
- [x] 实现手动重新投递
- [x] 实现回调测试接口
- [x] 实现回调 URL 基础 SSRF 防护和禁重定向
- [x] 通过出口代理或网络策略防护 DNS 重绑定
- [x] 保证回调失败不修改任务成功状态
- [x] 保证同一内部事件只物化一个回调投递
- [x] 增加真实接收方重复投递幂等端到端测试

## P1：实时事件

- [x] 实现全局 SSE 事件流
- [x] 实现单任务 SSE 事件流
- [x] 使用 Authorization Header 鉴权
- [x] 实现断线重连和 Last-Event-ID
- [x] 实现事件保留和过期策略，并保护尚未物化的回调源事件
- [x] 实现 SSE 慢消费者发送阻塞阈值和基于 Last-Event-ID 的安全重连
- [x] 增加任务和 Worker 实时事件查询及 SSE 格式测试

## P1：MCP

- [x] 建立无状态 Streamable HTTP MCP Server
- [x] 复用 HTTP API 的 Schema、仓储和 Storage
- [x] 实现 `parser_submit`
- [x] 实现 `parser_get_task`
- [x] 实现 `parser_get_result`
- [x] 实现 `parser_cancel_task`
- [x] 实现 `parser_list_capabilities`
- [x] 实现 `parser_list_pipelines`
- [x] 实现 `parser_list_backends`
- [x] 实现任务、结果、能力、Pipeline 和 Backend Resources
- [x] 使用普通 API Key 鉴权
- [x] 限制 MCP 直接传输大型文件，使用 HTTP `file_id`
- [x] 增加 MCP 与 HTTP Schema 复用及协议契约测试

## P1：Web UI

- [x] 初始化 Vue 3、TypeScript 和 Vite
- [x] 接入 shadcn-vue 配置及首批开放组件
- [x] 接入 Tailwind CSS
- [x] 接入 Vue Router、Pinia 和 TanStack Query
- [x] 声明 ECharts 依赖（图表组件待实现）
- [x] 从 OpenAPI 自动生成 TypeScript 类型和 API Client
- [x] 实现 API 地址和 API Key 连接页
- [x] API Key 默认只保存在当前浏览器会话
- [x] 实现整体布局和导航
- [x] 实现文件、URL、对象存储和文本测试输入
- [x] 实现 Pipeline、Backend 和硬件偏好选择
- [x] 实现解析特性配置
- [x] 实现带 `Authorization`/`Last-Event-ID` 的 SSE Stage 实时进度，并保留轮询兜底
- [x] 实现 JSON、文本、Markdown 原文和表格预览
- [x] 实现音视频 Transcript/Keyframe 时间轴和浏览器媒体预览
- [x] 实现带鉴权的 Artifact 文本、JSON、图片、音频、视频、PDF 预览和下载
- [x] 实现类型化请求 JSON、cURL 预览和复制 API 请求
- [x] 实现任务查询页面
- [x] 实现任务详情、取消和失败/取消任务重试页面
- [x] 实现 Worker 查询和 Drain 管理基础页面
- [x] 实现 Pipeline 草稿创建、校验、发布和历史版本回滚页面
- [x] 实现 Backend 注册、查询和启停管理页面
- [x] 实现回调测试、投递记录、逐次尝试历史和失败重试页面
- [x] 实现 API Key 创建、轮换、启停和删除页面
- [x] 实现带数据库覆盖来源说明的动态系统设置页面
- [x] 实现任务、Worker、Backend、硬件和回调看板
- [x] 建立独立 `parser-web` Dockerfile（依赖锁文件和生产构建验证待完成）

## P2：NVIDIA CUDA

- [x] 建立 `parser-worker-cuda` 独立 Dockerfile（厂商基础镜像和设备端构建待验证）
- [x] 实现 NVIDIA 多设备、显存、利用率和温度探测
- [x] 实现 CUDA Worker 设备与配置引擎能力上报
- [x] 通过 Remote Backend 1.0 类型化预设接入 PaddleOCR CUDA Backend
- [x] 通过 Remote Backend 1.0 类型化预设接入 MinerU CUDA Backend
- [x] 通过 Remote Backend 1.0 类型化预设接入 ASR CUDA Backend
- [x] 通过 Remote Backend 1.0 类型化预设接入图像与视频 VLM CUDA Backend
- [x] 实现模型预加载和卸载
- [x] 实现基于心跳显存/内存阈值的设备新租约保护和自动恢复
- [x] 实现 Worker Backend 级并发限制
- [x] 评估并实现可选 Ray Serve Executor
- [x] 增加保留 Runtime 偏好顺序的 GPU 优先与 CPU 自动降级策略
- [x] 增加多 GPU 调度和稳定性测试

## P2：国产硬件

- [ ] 确定首个实际接入的国产硬件平台
- [ ] 定义厂商运行时版本和驱动兼容矩阵
- [x] 为 Ascend、MLU、DCU、MUSA、XPU 建立互不继承的专用 Dockerfile
- [ ] 实现设备、内存和利用率探测
- [ ] 接入至少一个可用 OCR、ASR 或 VLM Backend
- [ ] 验证 Backend 能力注册
- [ ] 验证异构调度和故障降级
- [ ] 增加对应硬件端到端测试
- [ ] 按实际需求依次支持 Ascend、MLU、DCU、MUSA 和 XPU
- [x] 通过静态契约测试禁止国产硬件镜像继承 CUDA Worker 镜像

## P2：默认 Pipeline

- [x] 定义并实现 `document.auto` 默认 Pipeline（内置 PDF/Office Backend 可用时发布）
- [x] 定义 `image.ocr` 默认 Pipeline（OCR Backend 接入前保持 Draft）
- [x] 定义 `image.multimodal` 默认 Pipeline（VLM Backend 接入前保持 Draft）
- [x] 定义 `audio.transcription` 默认 Pipeline（ASR Backend 接入前保持 Draft）
- [x] 定义 `video.multimodal` 默认 Pipeline（视频 VLM Backend 接入前保持 Draft）
- [x] 实现内置 Backend 与默认 Pipeline 的 APIKey 管理接口幂等初始化
- [x] 实现基于内置 HTML Backend 的 `web.static`
- [x] 实现基于 Remote Backend 1.0、默认保持 Draft 的 `web.rendered`
- [x] 为每个默认 Pipeline 定义版本、超时和可用的 Backend 降级顺序
- [x] 为每个 Pipeline 增加端到端样本

## P2：可观测性

- [x] 实现控制面和 Worker JSON 结构化日志
- [x] 在 HTTP 访问和 Worker 执行日志中关联 request、task、stage 和 worker
- [x] 暴露普通 API Key 保护的 Prometheus 指标
- [x] 通过管理看板统计任务成功率和延迟分位数
- [x] 通过管理看板统计 Worker 心跳和资源利用率
- [x] 通过管理看板统计 Backend 调用、错误和降级
- [x] 通过管理看板及 Prometheus 统计回调投递和重试
- [x] 接入 OpenTelemetry
- [x] 实现跨 API、Task、Stage、Worker 和 Callback 的 Trace
- [x] 配置基础告警规则

## P2：安全

- [x] 实现上传、URL、S3/MinIO 的扩展名、MIME 和内容签名联合校验
- [x] 限制文件大小、PDF 页数、图片像素、媒体时长和 Stage 执行时间
- [x] 实现 Office ZIP 条目数、解压总量、单 XML 大小和压缩比炸弹防护
- [x] 实现本地 Storage、S3 Key 和 Office Archive 路径穿越防护
- [x] 实现 URL SSRF 防护（应用层逐跳校验，并提供排除私网地址的 Helm 出口网络策略）
- [x] 使用每 Stage 独立 TemporaryDirectory 并在执行后自动清理
- [x] 实现解析子进程资源限制
- [x] 对 S3/MinIO Artifact 使用有界有效期的短期签名 URL
- [x] 对 Worker 内部接口增加网络策略
- [x] 增加签名伪装、完整性损坏、超限 Archive、压缩炸弹和路径穿越样本测试

## P3：部署与发布

- [x] 建立 `parser-control-plane` 独立 Dockerfile（实际构建待验证）
- [x] 建立各硬件 Worker 独立 Dockerfile
- [x] 建立本地开发 Docker Compose，包含迁移和默认目录初始化 Job
- [x] 在 Compose 中加入 PostgreSQL、Redis、MinIO 及健康检查
- [x] 建立控制面、Web、迁移 Job 和异构 Worker Helm Chart
- [x] 配置 CPU、CUDA、Ascend、MLU、DCU、MUSA、XPU Node Selector 和设备资源
- [x] 实现 Helm pre-install/pre-upgrade Alembic 数据库迁移发布流程
- [x] 实现 Worker SIGTERM 自助 Drain、停止新租约并等待当前 Stage 的滚动升级语义
- [x] 实现应用/API/结果 Schema 版本和构建提交、构建时间信息接口
- [x] 生成 Python SDK
- [x] 生成 TypeScript SDK
- [x] 编写 Kubernetes 部署、升级、回滚和故障处理文档
- [ ] 完成容量、压力和故障恢复测试
- [ ] 发布首个可用版本

## 完成定义

每个功能完成时必须满足：

- [x] 请求、响应和事件具有完整 Schema
- [ ] 正常、异常和边界测试通过
- [x] 错误码稳定并有说明
- [ ] 日志和指标足以定位问题
- [ ] OpenAPI 和相关文档已更新
- [ ] 不引入未确认的协议破坏性变更
- [ ] 适用时已在 Web UI 中提供测试或管理能力
