import { onBeforeUnmount, ref, watch, type Ref } from "vue"

import type { TaskStatus } from "@/api/client"
import { useConnectionStore } from "@/stores/connection"

type EventEnvelope = {
  schema_version: string
  event_id: string
  occurred_at: string
  payload: { type: string; task_id?: string }
}

const terminalStatuses = new Set<TaskStatus>([
  "succeeded",
  "failed",
  "cancelled",
])

export function useTaskEvents(
  taskId: Ref<string>,
  status: Ref<TaskStatus | undefined>,
  onEvent: (event: EventEnvelope) => void,
) {
  const connection = useConnectionStore()
  const connected = ref(false)
  const error = ref<string | null>(null)
  let controller: AbortController | null = null
  let lastEventId: string | null = null
  let reconnectTimer: number | null = null

  function stop() {
    controller?.abort()
    controller = null
    connected.value = false
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  function scheduleReconnect() {
    if (status.value && terminalStatuses.has(status.value)) return
    reconnectTimer = window.setTimeout(connect, 3_000)
  }

  async function connect() {
    stop()
    if (!taskId.value || (status.value && terminalStatuses.has(status.value))) return
    controller = new AbortController()
    const headers = new Headers({
      Accept: "text/event-stream",
      Authorization: `Bearer ${connection.apiKey}`,
    })
    if (lastEventId) headers.set("Last-Event-ID", lastEventId)

    try {
      const response = await fetch(
        `${connection.apiUrl}/api/v1/tasks/${encodeURIComponent(taskId.value)}/events/stream`,
        { headers, signal: controller.signal },
      )
      if (response.status === 404 && lastEventId) {
        lastEventId = null
        throw new Error("SSE resume cursor expired; reconnecting from current events")
      }
      if (!response.ok || !response.body) {
        throw new Error(`SSE HTTP ${response.status}`)
      }
      connected.value = true
      error.value = null
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n")
        let boundary = buffer.indexOf("\n\n")
        while (boundary >= 0) {
          const frame = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          const lines = frame.split("\n")
          const id = lines.find((line) => line.startsWith("id:"))?.slice(3).trim()
          const data = lines
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart())
            .join("\n")
          if (id) lastEventId = id
          if (data) onEvent(JSON.parse(data) as EventEnvelope)
          boundary = buffer.indexOf("\n\n")
        }
      }
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        error.value = reason instanceof Error ? reason.message : "SSE disconnected"
      }
    } finally {
      connected.value = false
      controller = null
      scheduleReconnect()
    }
  }

  watch(taskId, () => {
    lastEventId = null
    void connect()
  })
  watch(status, (next) => {
    if (next && terminalStatuses.has(next)) stop()
    else if (!controller && reconnectTimer === null) void connect()
  })
  void connect()
  onBeforeUnmount(stop)

  return { connected, error, reconnect: connect, stop }
}
