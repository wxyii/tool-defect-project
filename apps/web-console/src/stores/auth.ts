import { computed, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { MemorySession, StaleSessionError } from '@/auth/memory-session'
import type {
  AuthIdentity,
  AuthSession,
  TokenRefreshProvider,
} from '@/auth/types'

/** 旧测试隔离容器；生产请求与登录流程不读取其中令牌。 */
export const memorySession = new MemorySession()

export const useAuthStore = defineStore('auth', () => {
  const identity = shallowRef<AuthIdentity | null>(null)
  const initialized = shallowRef(false)
  const authenticated = computed(() => identity.value !== null)

  function establish(value: AuthIdentity | AuthSession): void {
    const resolved = 'identity' in value ? value.identity : value
    if ('identity' in value) {
      memorySession.set(value)
    }
    identity.value = Object.freeze(resolved)
    initialized.value = true
  }

  function clear(): void {
    identity.value = null
    memorySession.clear()
    initialized.value = true
  }

  function hasPermission(permission: string): boolean {
    return identity.value?.permissions.includes(permission) ?? false
  }

  function hasEveryPermission(permissions: readonly string[]): boolean {
    return permissions.every(hasPermission)
  }

  async function refresh(provider: TokenRefreshProvider): Promise<void> {
    try {
      await memorySession.refresh(provider)
    } catch (error) {
      if (!(error instanceof StaleSessionError)) clear()
      throw error
    }
  }

  return {
    identity,
    initialized,
    authenticated,
    establish,
    clear,
    hasPermission,
    hasEveryPermission,
    refresh,
  }
})
