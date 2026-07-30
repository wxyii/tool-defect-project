import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MemorySession } from '@/auth/memory-session'
import type { AuthSession, AuthTokens } from '@/auth/types'
import { memorySession, useAuthStore } from '@/stores/auth'

const session: AuthSession = {
  identity: {
    subject: 'user-1',
    displayName: '质量负责人',
    roles: ['QUALITY_MANAGER'],
    permissions: ['detection:read', 'quality:read'],
  },
  tokens: {
    accessToken: 'access-secret',
    refreshToken: 'refresh-secret',
    expiresAtEpochMs: 10_000,
  },
}

describe('内存认证会话', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    memorySession.clear()
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  it('建立会话时不写浏览器长期存储', () => {
    const localSpy = vi.spyOn(Storage.prototype, 'setItem')
    const auth = useAuthStore()

    auth.establish(session)

    expect(auth.authenticated).toBe(true)
    expect(auth.hasPermission('quality:read')).toBe(true)
    expect(localSpy).not.toHaveBeenCalled()
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
  })

  it('并发刷新只执行一次并更新内存令牌', async () => {
    const memory = new MemorySession()
    memory.set(session)
    let calls = 0
    const provider = {
      async refresh() {
        calls += 1
        await Promise.resolve()
        return {
          accessToken: 'new-access',
          refreshToken: 'new-refresh',
          expiresAtEpochMs: 20_000,
        }
      },
    }

    const [first, second] = await Promise.all([
      memory.refresh(provider),
      memory.refresh(provider),
    ])

    expect(calls).toBe(1)
    expect(first.accessToken).toBe('new-access')
    expect(second.accessToken).toBe('new-access')
    expect(memory.accessToken).toBe('new-access')
  })

  it('退出会清除全部内存认证信息', () => {
    const auth = useAuthStore()
    auth.establish(session)
    auth.clear()
    expect(auth.authenticated).toBe(false)
    expect(auth.identity).toBeNull()
    expect(memorySession.accessToken).toBeNull()
  })

  it('旧会话刷新完成后不能覆盖新会话或清除新刷新锁', async () => {
    const memory = new MemorySession()
    memory.set(session)
    const oldRefresh = deferred<AuthTokens>()
    const newRefresh = deferred<AuthTokens>()
    const oldProvider = {
      refresh: vi.fn(() => oldRefresh.promise),
    }
    const newProvider = {
      refresh: vi.fn(() => newRefresh.promise),
    }

    const oldOperation = memory.refresh(oldProvider)
    memory.clear()
    memory.set({
      identity: {
        subject: 'user-2',
        displayName: '复核员',
        roles: ['REVIEWER'],
        permissions: ['review:read'],
      },
      tokens: {
        accessToken: 'user-two-access',
        refreshToken: 'user-two-refresh',
        expiresAtEpochMs: 30_000,
      },
    })
    const firstNewOperation = memory.refresh(newProvider)
    oldRefresh.resolve({
      accessToken: 'stale-access',
      refreshToken: 'stale-refresh',
      expiresAtEpochMs: 40_000,
    })

    await expect(oldOperation).rejects.toThrow('TD-AUTH-SESSION-STALE-001')
    const secondNewOperation = memory.refresh(newProvider)
    expect(newProvider.refresh).toHaveBeenCalledOnce()
    newRefresh.resolve({
      accessToken: 'fresh-user-two-access',
      refreshToken: 'fresh-user-two-refresh',
      expiresAtEpochMs: 50_000,
    })
    await expect(firstNewOperation).resolves.toMatchObject({
      accessToken: 'fresh-user-two-access',
    })
    await expect(secondNewOperation).resolves.toMatchObject({
      accessToken: 'fresh-user-two-access',
    })
    expect(memory.session?.identity.subject).toBe('user-2')
    expect(memory.accessToken).toBe('fresh-user-two-access')
  })

  it('store 的旧刷新失败不会清除后来建立的身份', async () => {
    const auth = useAuthStore()
    auth.establish(session)
    const refreshResult = deferred<AuthTokens>()
    const operation = auth.refresh({
      refresh: vi.fn(() => refreshResult.promise),
    })
    auth.clear()
    auth.establish({
      identity: {
        subject: 'user-2',
        displayName: '复核员',
        roles: ['REVIEWER'],
        permissions: ['review:read'],
      },
      tokens: {
        accessToken: 'user-two-access',
        refreshToken: 'user-two-refresh',
        expiresAtEpochMs: 30_000,
      },
    })
    refreshResult.resolve({
      accessToken: 'stale-access',
      refreshToken: 'stale-refresh',
      expiresAtEpochMs: 40_000,
    })

    await expect(operation).rejects.toThrow('TD-AUTH-SESSION-STALE-001')
    expect(auth.identity?.subject).toBe('user-2')
    expect(memorySession.accessToken).toBe('user-two-access')
  })
})

function deferred<T>(): {
  readonly promise: Promise<T>
  readonly resolve: (value: T) => void
} {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => {
    resolve = accept
  })
  return { promise, resolve }
}
