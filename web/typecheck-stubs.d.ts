declare module "pinia" {
  import type { Ref } from "vue"

  type UnwrapRefs<T> = {
    [K in keyof T]: T[K] extends Ref<infer Value> ? Value : T[K]
  }

  export function defineStore<T>(
    name: string,
    setup: () => T,
  ): () => UnwrapRefs<T>
}

declare module "vue" {
  export interface Ref<T> {
    value: T
  }

  export function ref<T>(value: T): Ref<T>
  export function computed<T>(getter: () => T): Readonly<Ref<T>>
}
