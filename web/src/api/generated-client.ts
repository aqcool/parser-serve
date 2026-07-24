import {
  operationSpecs,
  type OperationId,
  type OperationResponse,
  type operations,
} from "./generated"

export type GeneratedOperationArgs<T extends OperationId> = {
  path?: operations[T]["parameters"]["path"]
  query?: operations[T]["parameters"]["query"]
  header?: operations[T]["parameters"]["header"]
  body?: operations[T]["requestBody"] | FormData
  signal?: AbortSignal
}

export class GeneratedApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

export type ParserServeClientOptions = {
  baseUrl: string
  apiKey: string
  fetch?: typeof globalThis.fetch
}

function appendQuery(
  url: URL,
  values: Record<string, unknown> | undefined,
) {
  if (!values) return
  for (const [name, value] of Object.entries(values)) {
    if (value === undefined || value === null) continue
    if (Array.isArray(value)) {
      for (const item of value) url.searchParams.append(name, String(item))
    } else {
      url.searchParams.set(name, String(value))
    }
  }
}

export class ParserServeClient {
  private readonly baseUrl: string
  private readonly apiKey: string
  private readonly fetchImplementation: typeof globalThis.fetch

  constructor(options: ParserServeClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "")
    this.apiKey = options.apiKey
    this.fetchImplementation = options.fetch ?? globalThis.fetch
  }

  async request<T extends OperationId>(
    operationId: T,
    args: GeneratedOperationArgs<T> = {},
  ): Promise<OperationResponse<T>> {
    const specification = operationSpecs[operationId]
    let path: string = specification.path
    for (const [name, value] of Object.entries(args.path ?? {})) {
      path = path.replace(`{${name}}`, encodeURIComponent(String(value)))
    }
    if (path.includes("{")) {
      throw new Error(`Missing path parameter for ${operationId}`)
    }

    const url = new URL(path, `${this.baseUrl}/`)
    appendQuery(url, args.query)
    const headers = new Headers()
    headers.set("Authorization", `Bearer ${this.apiKey}`)
    for (const [name, value] of Object.entries(args.header ?? {})) {
      if (value !== undefined && value !== null) headers.set(name, String(value))
    }

    let body: BodyInit | undefined
    if (args.body instanceof FormData) {
      body = args.body
    } else if (args.body !== undefined) {
      headers.set("Content-Type", "application/json")
      body = JSON.stringify(args.body)
    }
    const response = await this.fetchImplementation(url, {
      method: specification.method,
      headers,
      ...(body !== undefined ? { body } : {}),
      ...(args.signal !== undefined ? { signal: args.signal } : {}),
    })
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as {
        error?: { code?: string; message?: string }
      } | null
      throw new GeneratedApiError(
        response.status,
        payload?.error?.code ?? "HTTP_ERROR",
        payload?.error?.message ?? `Request failed with HTTP ${response.status}`,
      )
    }
    if (response.status === 204) {
      return undefined as unknown as OperationResponse<T>
    }
    const contentType = response.headers.get("Content-Type") ?? ""
    if (contentType.includes("application/json")) {
      return (await response.json()) as OperationResponse<T>
    }
    return (await response.blob()) as unknown as OperationResponse<T>
  }
}
