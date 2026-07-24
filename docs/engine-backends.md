# 解析引擎接入

`parser_serve.backends` 是统一解析实现包。控制面只登记能力和调度 Stage，
实际 PaddleOCR、PaddleOCR-VL、HunyuanOCR、MinerU、ASR、VLM 与动态网页
渲染服务由匹配硬件的 Worker 调用。

## 引擎预设

| `engine` | Backend 名称 | 默认媒体能力 |
| --- | --- | --- |
| `paddleocr` | `paddleocr` | image、document |
| `paddleocr_vl` | `paddleocr_vl` | image、document |
| `hunyuan_ocr` | `hunyuan_ocr` | image、document |
| `mineru` | `mineru` | document |
| `asr` | `asr` | audio |
| `vlm` | `vlm` | image |
| `video_vlm` | `video_vlm` | video |
| `web_rendered` | `web_rendered` | web |

这些名称与默认 Pipeline 完全一致。使用预设后不需要重复填写
`media_categories`、`mime_types` 或 Backend 名称。

## Worker 配置

通过 Pydantic Settings JSON 配置一个或多个引擎：

```bash
PARSER_WORKER_ENGINE_BACKENDS='[
  {
    "engine": "paddleocr",
    "endpoint": "http://paddleocr:8080/v1/parse",
    "maximum_concurrency": 4,
    "timeout_seconds": 300
  },
  {
    "engine": "mineru",
    "endpoint": "http://mineru:8080/v1/parse",
    "authentication": {
      "type": "bearer",
      "token": "replace-with-secret-token"
    },
    "timeout_seconds": 900
  }
]' \
uv run --extra worker-cuda parser-worker
```

Worker 将预设转换成标准 `RemoteBackendConfig`，并使用 Remote Backend 1.0
协议执行。认证 Token 只存在于 Worker，不进入控制面数据库、注册能力或日志。

同一 Worker 中，`engine_backends` 与通用 `remote_backends` 的
`(name, version)` 不能重复。

Worker 能力上报后，还需通过普通 API Key 在控制面的 Backend Registry 创建
同名、同版本和同 Runtime 的逻辑 Backend，然后校验并发布引用它的 Pipeline。
这一步保持为显式管理操作，避免持有 Worker Key 的节点擅自修改全局路由目录。
注册请求示例见[远程 Backend 协议](remote-backends.md#3-控制面-backend-注册)。

`web_rendered` 用于接入基于 Playwright、Chromium 或其他沙箱浏览器实现的
Remote Backend。请求中的 `source.attributes.source_url` 是经过 Worker
SSRF 校验的原始 URL，上传的 HTML 文件是静态抓取快照；渲染服务应按自身
网络策略决定是否重新访问原始 URL，并返回标准 `ParseResult`。

## 硬件镜像边界

解析模型服务可以：

1. 与 Worker 位于同一 Pod/机器，通过回环或内部网络调用；
2. 独立部署为模型服务，由多个 Worker 访问；
3. 使用厂商运行时镜像部署，再由对应 CUDA、Ascend、MLU、DCU、MUSA 或 XPU
   Worker 接入。

Parser Serve 不在基础依赖中同时安装所有模型 SDK。控制面使用
`control-plane` Profile，每个 Worker 只安装一个硬件 Profile；模型服务自身
的 Paddle、MinerU、PyTorch 或厂商 SDK 应留在其独立镜像中。这能避免 CUDA 与
国产运行时依赖互相污染，也允许同一个调度协议跨不同硬件实现。

## Remote Backend 1.0 要求

引擎端必须实现 `multipart/form-data` 的 `POST /v1/parse`：

- `request` Part 为严格的 `RemoteParseRequest` JSON；
- 文件 Source 使用额外 `file` Part；
- 成功返回 `RemoteParseSucceeded`；
- 失败返回 `RemoteParseFailed`；
- `ParseResult.task_id` 和 Source 元数据必须与请求一致；
- Artifact 内容必须通过受限 Base64 Payload 返回。

完整协议、大小限制和错误处理见 [远程 Backend 协议](remote-backends.md)。
