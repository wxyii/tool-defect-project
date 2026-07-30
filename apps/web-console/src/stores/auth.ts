import { computed, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { MemorySession, StaleSessionError } from '@/auth/memory-session'
import type {
  AuthIdentity,
  AuthSession,
  TokenRefreshProvider,
} from '@/auth/types'

export const memorySession = new MemorySession()

export const useAuthStore = defineStore('auth', () => {
  const identity = shallowRef<AuthIdentity | null>(null)
  const authenticated = computed(
    () => identity.value !== null && memorySession.session !== null,
  )

  function establish(session: AuthSession): void {
    memorySession.set(session)
    identity.value = session.identity
  }

  function clear(): void {
    memorySession.clear()
    identity.value = null
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
      if (!(error instanceof StaleSessionError)) {
        clear()
      }
      throw error
    }
  }

  return {
    identity,
    authenticated,
    establish,
    clear,
    hasPermission,
    hasEveryPermission,
    refresh,
  }
})
