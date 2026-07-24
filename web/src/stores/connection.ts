import { defineStore } from "pinia"
import { computed, ref } from "vue"

const STORAGE_KEY = "parser-serve-connection"

type StoredConnection = {
  apiUrl: string
  apiKey: string
}

function restore(): StoredConnection {
  const value = sessionStorage.getItem(STORAGE_KEY)
  if (!value) return { apiUrl: window.location.origin, apiKey: "" }
  try {
    return JSON.parse(value) as StoredConnection
  } catch {
    return { apiUrl: window.location.origin, apiKey: "" }
  }
}

export const useConnectionStore = defineStore("connection", () => {
  const initial = restore()
  const apiUrl = ref(initial.apiUrl)
  const apiKey = ref(initial.apiKey)
  const connected = computed(() => apiKey.value.length > 0)

  function save(nextUrl: string, nextKey: string) {
    apiUrl.value = nextUrl.replace(/\/+$/, "")
    apiKey.value = nextKey
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ apiUrl: apiUrl.value, apiKey: apiKey.value }),
    )
  }

  function clear() {
    apiKey.value = ""
    sessionStorage.removeItem(STORAGE_KEY)
  }

  return { apiUrl, apiKey, connected, save, clear }
})
