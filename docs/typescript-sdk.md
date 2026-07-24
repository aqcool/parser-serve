# TypeScript SDK

仓库从 `web/openapi.json` 确定性生成：

- `web/src/api/generated.ts`：全部组件 Schema、65 个 operationId 的 Path、
  Query、Header、请求体、成功响应类型，以及运行时方法/路径表；
- `web/src/api/generated-client.ts`：不依赖 Vue、Pinia 或其他运行时库的
  `ParserServeClient`。

生成器只依赖项目 Python 环境，不需要安装 npm 包：

```bash
PYTHONPATH=. uv run python -m scripts.export_openapi
uv run python -m scripts.generate_typescript_sdk
uv run python -m scripts.generate_typescript_sdk --check
```

`--check` 不修改文件，生成结果与提交内容不一致时返回失败。CI 同时校验
OpenAPI 快照和 SDK，防止后端接口变化后遗漏更新。

## 使用

```ts
import { ParserServeClient } from "./generated-client"

const client = new ParserServeClient({
  baseUrl: "https://parser.example.com",
  apiKey: "parser_replace_me",
})

const created = await client.request("create_task", {
  header: { "Idempotency-Key": "order-20260724-001" },
  body: {
    source: {
      type: "text",
      text: "需要解析的内容",
      mime_type: "text/plain",
    },
  },
})

const task = await client.request("get_task", {
  path: { task_id: created.data.task_id },
})
```

operationId、参数名、枚举、必填性和响应均由 OpenAPI 推导。缺少 Path 参数会
在发出请求前报错；数组 Query 参数会编码为重复 Key；普通对象请求体使用 JSON；
上传接口接受 `FormData`；非 JSON 成功响应返回 `Blob`。

失败响应抛出 `GeneratedApiError`，包含稳定的 HTTP `status`、业务 `code`
和诊断 `message`。调用方应遵守[错误码契约](error-codes.md)，不要匹配
`message`。

## Web UI 集成

`web/src/api/client.ts` 保留面向页面的 `parserApi` 方法名，但任务、Worker、
Backend、Pipeline、Callback、API Key、设置、保留策略和文件上传都通过
`ParserServeClient.request(operationId)` 执行。页面不再维护这些接口的 URL
拼接；Artifact 预览的通用流式 Fetch 仍由 UI 封装，因为它还负责 Object URL
生命周期和媒体预览。

SDK 自身可在不安装 Vue 依赖的情况下检查：

```bash
cd web
npm run check:sdk
```

完整 Web UI 构建仍需要先安装 `package.json` 中的前端依赖。
