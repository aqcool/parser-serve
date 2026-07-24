# 默认 Pipeline 与端到端样本

默认目录通过 `POST /api/v1/management/defaults/initialize` 幂等安装。内置
Backend 可用的 Pipeline 会自动发布；依赖尚未注册模型服务的 Pipeline 保持
Draft。后续注册对应 Backend 后再次初始化，会校验并发布原版本，不需要删除
目录记录。

| Pipeline | 输入 | 首选与降级顺序 | 默认状态条件 |
| --- | --- | --- | --- |
| `document.auto` | PDF、DOCX、PPTX、XLSX | MinerU → PaddleOCR-VL → HunyuanOCR → 内置 PDF → 内置 Office | 至少一个兼容 Backend 可用 |
| `web.static` | HTML、XHTML | 内置静态 HTML | 安装内置 Backend 后发布 |
| `web.rendered` | HTML、XHTML | Remote Web Rendered | 注册动态渲染 Backend 后发布 |
| `image.ocr` | 图片 | PaddleOCR → HunyuanOCR → PaddleOCR-VL | 注册至少一个兼容 OCR Backend 后发布 |
| `image.multimodal` | 图片 | PaddleOCR-VL → HunyuanOCR → VLM | 注册至少一个兼容 VLM/OCR Backend 后发布 |
| `audio.transcription` | 音频 | ASR | 注册 ASR Backend 后发布 |
| `video.multimodal` | 视频 | Video VLM → VLM | 注册兼容 Video VLM Backend 后发布 |

Pipeline 测试接口可以显式执行 Draft 或 Published 的指定版本，不改变发布状态：

```bash
curl -X POST \
  http://localhost:8000/api/v1/management/pipelines/pipeline_image_ocr/versions/1/test \
  -H "Authorization: Bearer $PARSER_SERVE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source": {
      "type": "uploaded_file",
      "file_id": "file_replace_me"
    },
    "client_reference": "pipeline-smoke-image-ocr"
  }'
```

接口会创建真实 Task 和 Stage，并经过正常路由、租约、Worker、Artifact 和结果
链路。它不绕过 Backend 能力或输入 MIME 校验。

## 仓库端到端覆盖

`tests/test_default_pipeline_e2e.py` 使用五类有合法签名的内存样本：

- PDF；
- HTML；
- PNG；
- WAV；
- MP4。

测试先注册 MinerU、Web Rendered、PaddleOCR、PaddleOCR-VL、ASR 和 Video VLM
能力，再启动真实本地 TCP Remote Backend 1.0 接收器。七个默认 Pipeline
分别通过管理测试接口创建 Task，Worker 一次拉取多个租约，下载并复验源文件，
调用内置或远程 Backend，上传 Artifact，完成 Stage，最后从结果 API 读取严格
`ParseResult`。

另一个样本不注册任何模型 Backend，使用真实 DOCX ZIP 内容验证
`document.auto` 跳过不可用的首选项并执行内置 Office fallback。

这些测试证明 Parser Serve 的目录、协议和执行链路兼容，不代表第三方引擎本身
的识别质量或目标硬件可用。发布前仍必须把本地协议接收器替换为实际厂商服务，
使用业务数据集验证精度、延迟、资源使用和失败恢复。
