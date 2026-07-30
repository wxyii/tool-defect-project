import { beforeEach, describe, expect, it, vi } from 'vitest'

import { bootstrapOidcCallback } from '@/auth/bootstrap'
import {
  HttpOidcTransport,
  OidcAuthorizationCoordinator,
  type OidcClientConfiguration,
  OidcSessionProvider,
  SessionStorageAuthorizationTransactionStore,
  type AuthorizationTransaction,
  type AuthorizationTransactionStore,
} from '@/auth/oidc'
import { createOidcRuntimeFromEnvironment } from '@/auth/runtime'
import type { AuthSession } from '@/auth/types'
import { memorySession } from '@/stores/auth'

const configuration: OidcClientConfiguration = {
  authorizationEndpoint: 'https://identity.invalid/oauth2/authorize',
  tokenEndpoint: 'https://identity.invalid/oauth2/token',
  userInfoEndpoint: 'https://identity.invalid/oauth2/userinfo',
  revocationEndpoint: 'https://identity.invalid/oauth2/revoke',
  clientId: 'tool-defect-web',
  redirectUri: 'https://console.invalid/auth/callback',
  scopes: ['openid', 'profile', 'offline_access'],
}

const session: AuthSession = {
  identity: {
    subject: 'quality-1',
    displayName: '质量负责人',
    roles: ['QUALITY_MANAGER'],
    permissions: ['quality:read'],
  },
  tokens: {
    accessToken: 'access-token',
    refreshToken: 'refresh-token',
    expiresAtEpochMs: 61_000,
  },
}

describe('OIDC 授权码与会话引导', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    memorySession.clear()
  })

  it('生成带状态和校验挑战的授权请求并安全恢复回调', async () => {
    const transactions = new MemoryTransactionStore()
    const transport = {
      exchangeAuthorizationCode: vi.fn(async () => session),
      refresh: vi.fn(),
      revoke: vi.fn(),
    }
    const coordinator = new OidcAuthorizationCoordinator(
      configuration,
      new OidcSessionProvider(transport),
      transactions,
      {
        randomBytes: (length) => new Uint8Array(length).fill(7),
        digest: async () => new Uint8Array([1, 2, 3, 4]).buffer,
      },
    )

    const authorizationUrl = new URL(
      await coordinator.createAuthorizationRequest('/quality?station=one'),
    )
    expect(authorizationUrl.origin).toBe('https://identity.invalid')
    expect(authorizationUrl.searchParams.get('response_type')).toBe('code')
    expect(authorizationUrl.searchParams.get('code_challenge_method')).toBe('S256')
    expect(authorizationUrl.searchParams.get('code_challenge')).toBe('AQIDBA')
    const state = authorizationUrl.searchParams.get('state')
    expect(state).not.toBeNull()

    const result = await coordinator.completeAuthorizationCallback(
      `https://console.invalid/auth/callback?code=authorization-code&state=${state}`,
    )
    expect(result).toEqual({
      session,
      redirectAfterLogin: '/quality?station=one',
    })
    expect(transport.exchangeAuthorizationCode).toHaveBeenCalledWith(
      'authorization-code',
      expect.stringMatching(/^BwcH/),
    )
    await expect(
      coordinator.completeAuthorizationCallback(
        `https://console.invalid/auth/callback?code=replay&state=${state}`,
      ),
    ).rejects.toThrow('TD-AUTH-TRANSACTION-001')
  })

  it('状态不匹配时单次事务失效且不会交换授权码', async () => {
    const transport = {
      exchangeAuthorizationCode: vi.fn(async () => session),
      refresh: vi.fn(),
      revoke: vi.fn(),
    }
    const transactions = new MemoryTransactionStore()
    transactions.save({
      state: 'expected-state',
      codeVerifier: 'v'.repeat(64),
      redirectAfterLogin: '/workstation',
    })
    const coordinator = new OidcAuthorizationCoordinator(
      configuration,
      new OidcSessionProvider(transport),
      transactions,
    )

    await expect(
      coordinator.completeAuthorizationCallback(
        'https://console.invalid/auth/callback?code=code&state=wrong-state',
      ),
    ).rejects.toThrow('TD-AUTH-STATE-001')
    expect(transport.exchangeAuthorizationCode).not.toHaveBeenCalled()
    expect(transactions.take()).toBeNull()
  })

  it('回调成功建立内存会话，失败则明确清理', async () => {
    const auth = { establish: vi.fn(), clear: vi.fn() }
    const runtime = {
      configured: true,
      refreshProvider: { refresh: vi.fn() },
      createAuthorizationRequest: vi.fn(),
      completeAuthorizationCallback: vi.fn(async () => ({
        session,
        redirectAfterLogin: '/reviews',
      })),
      revokeSession: vi.fn(async () => undefined),
    }
    await expect(
      bootstrapOidcCallback(runtime, auth, 'https://console.invalid/auth/callback'),
    ).resolves.toBe('/reviews')
    expect(auth.establish).toHaveBeenCalledWith(session)

    runtime.completeAuthorizationCallback.mockRejectedValueOnce(
      new Error('TD-AUTH-CODE-001'),
    )
    await expect(
      bootstrapOidcCallback(runtime, auth, 'https://console.invalid/auth/callback'),
    ).rejects.toThrow('TD-AUTH-CODE-001')
    expect(auth.clear).toHaveBeenCalledOnce()
  })

  it('较早回调晚到时不能覆盖或清除较新的登录会话', async () => {
    const first = deferred<{
      readonly session: AuthSession
      readonly redirectAfterLogin: string
    }>()
    const second = deferred<{
      readonly session: AuthSession
      readonly redirectAfterLogin: string
    }>()
    const newerSession: AuthSession = {
      identity: {
        subject: 'newer-user',
        displayName: '较新用户',
        roles: ['REVIEWER'],
        permissions: ['review:read'],
      },
      tokens: {
        accessToken: 'newer-access',
        refreshToken: 'newer-refresh',
        expiresAtEpochMs: 120_000,
      },
    }
    let call = 0
    const runtime = {
      configured: true,
      refreshProvider: { refresh: vi.fn() },
      createAuthorizationRequest: vi.fn(),
      completeAuthorizationCallback: vi.fn(() => {
        call += 1
        return call === 1 ? first.promise : second.promise
      }),
      revokeSession: vi.fn(async () => undefined),
    }
    const auth = {
      establish: vi.fn((value: AuthSession) => memorySession.set(value)),
      clear: vi.fn(() => memorySession.clear()),
    }

    const earlier = bootstrapOidcCallback(runtime, auth, 'https://first.invalid')
    const newer = bootstrapOidcCallback(runtime, auth, 'https://second.invalid')
    second.resolve({
      session: newerSession,
      redirectAfterLogin: '/reviews',
    })
    await expect(newer).resolves.toBe('/reviews')
    first.resolve({
      session,
      redirectAfterLogin: '/workstation',
    })

    await expect(earlier).rejects.toThrow('TD-AUTH-SESSION-STALE-001')
    expect(memorySession.session?.identity.subject).toBe('newer-user')
    expect(memorySession.accessToken).toBe('newer-access')
    expect(auth.clear).not.toHaveBeenCalled()
  })

  it('标签页存储只暂存一次性校验事务并在读取前删除', () => {
    const store = new SessionStorageAuthorizationTransactionStore(
      window.sessionStorage,
    )
    const transaction = {
      state: 'state',
      codeVerifier: 'v'.repeat(64),
      redirectAfterLogin: '/workstation',
    }
    store.save(transaction)
    const serialized = window.sessionStorage.getItem(
      'tool-defect.oidc.authorization-transaction',
    )
    expect(serialized).not.toContain('accessToken')
    expect(serialized).not.toContain('refreshToken')
    expect(store.take()).toEqual(transaction)
    expect(window.sessionStorage.length).toBe(0)
  })
})

describe('OIDC HTTP 传输', () => {
  it('以表单交换授权码并从用户信息端点建立身份', async () => {
    let call = 0
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      call += 1
      if (call === 1) {
        const form = new URLSearchParams(String(init?.body))
        expect(form.get('grant_type')).toBe('authorization_code')
        expect(form.get('code_verifier')).toBe('v'.repeat(64))
        return Response.json({
          access_token: 'access-token',
          refresh_token: 'refresh-token',
          expires_in: 60,
        })
      }
      expect(new Headers(init?.headers).get('Authorization')).toBe(
        'Bearer access-token',
      )
      return Response.json({
        sub: 'quality-1',
        name: '质量负责人',
        roles: ['QUALITY_MANAGER'],
        permissions: ['quality:read'],
      })
    })
    const transport = new HttpOidcTransport(configuration, {
      fetcher: fetcher as typeof fetch,
      clock: () => 1_000,
    })

    await expect(
      transport.exchangeAuthorizationCode('code', 'v'.repeat(64)),
    ).resolves.toEqual(session)
  })

  it('缺少环境配置时显式不可用，不指向虚构后端', async () => {
    const runtime = createOidcRuntimeFromEnvironment(
      {} as ImportMetaEnv,
      window,
    )
    expect(runtime.configured).toBe(false)
    await expect(runtime.createAuthorizationRequest('/workstation')).rejects.toThrow(
      'TD-AUTH-CONFIG-001',
    )
  })

  it('拒绝明文外部控制台来源和缺少 openid 的伪 OIDC 配置', async () => {
    const environment = {
      VITE_OIDC_AUTHORIZATION_ENDPOINT:
        'https://identity.invalid/oauth2/authorize',
      VITE_OIDC_TOKEN_ENDPOINT: 'https://identity.invalid/oauth2/token',
      VITE_OIDC_USERINFO_ENDPOINT: 'https://identity.invalid/oauth2/userinfo',
      VITE_OIDC_CLIENT_ID: 'tool-defect-web',
    } as ImportMetaEnv
    const insecureBrowser = {
      location: { origin: 'http://console.invalid' },
      sessionStorage: window.sessionStorage,
    } as unknown as Pick<Window, 'location' | 'sessionStorage'>
    const insecureRuntime = createOidcRuntimeFromEnvironment(
      environment,
      insecureBrowser,
    )
    expect(insecureRuntime.configured).toBe(false)
    await expect(
      insecureRuntime.createAuthorizationRequest('/workstation'),
    ).rejects.toThrow('TD-AUTH-CONFIG-ORIGIN-001')

    const missingOpenIdRuntime = createOidcRuntimeFromEnvironment(
      {
        ...environment,
        VITE_OIDC_SCOPES: 'profile offline_access',
      } as ImportMetaEnv,
      window,
    )
    expect(missingOpenIdRuntime.configured).toBe(false)
    await expect(
      missingOpenIdRuntime.createAuthorizationRequest('/workstation'),
    ).rejects.toThrow('TD-AUTH-CONFIG-SCOPE-001')
  })

  it('运行时退出接口将刷新令牌发送到吊销端点', async () => {
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(null, { status: 200 }),
    )
    const runtime = createOidcRuntimeFromEnvironment(
      {
        VITE_OIDC_AUTHORIZATION_ENDPOINT:
          'https://identity.invalid/oauth2/authorize',
        VITE_OIDC_TOKEN_ENDPOINT: 'https://identity.invalid/oauth2/token',
        VITE_OIDC_USERINFO_ENDPOINT: 'https://identity.invalid/oauth2/userinfo',
        VITE_OIDC_REVOCATION_ENDPOINT:
          'https://identity.invalid/oauth2/revoke',
        VITE_OIDC_CLIENT_ID: 'tool-defect-web',
      } as ImportMetaEnv,
      window,
      fetcher as typeof fetch,
    )

    await runtime.revokeSession('refresh-to-revoke')
    expect(fetcher).toHaveBeenCalledOnce()
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      'https://identity.invalid/oauth2/revoke',
    )
    const request = fetcher.mock.calls[0]?.[1]
    expect(new URLSearchParams(String(request?.body)).get('token')).toBe(
      'refresh-to-revoke',
    )
  })
})

class MemoryTransactionStore implements AuthorizationTransactionStore {
  private value: AuthorizationTransaction | null = null

  save(transaction: AuthorizationTransaction): void {
    this.value = transaction
  }

  take(): AuthorizationTransaction | null {
    const value = this.value
    this.value = null
    return value
  }
}

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
