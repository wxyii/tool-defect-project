import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  changePassword,
  login,
  parseIdentity,
  restoreSession,
} from '@/auth/local-auth'
import { ApiClient } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const identity = {
  user_id: '10000000-0000-0000-0000-000000000001',
  username: 'operator',
  display_name: '操作员',
  roles: ['OPERATOR'],
  permissions: ['detection:read'],
  password_change_required: true,
}

describe('本地账号会话', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('解析后端身份并保留强制改密状态', () => {
    expect(parseIdentity(identity)).toMatchObject({
      username: 'operator',
      displayName: '操作员',
      passwordChangeRequired: true,
    })
  })

  it('登录前获取请求校验令牌并仅使用同源凭据', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'csrf-token' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(identity), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetcher)

    const result = await login('operator', 'long-enough-password')
    expect(result.username).toBe('operator')
    const loginInit = fetcher.mock.calls[1]?.[1] as RequestInit
    expect(loginInit.credentials).toBe('same-origin')
    expect(new Headers(loginInit.headers).get('X-TD-CSRF')).toBe('csrf-token')
    expect(new Headers(loginInit.headers).has('Authorization')).toBe(false)
  })

  it('未登录的会话恢复返回空值', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, {
      status: 401,
    })))
    await expect(restoreSession()).resolves.toBeNull()
  })

  it('改密使用下划线字段且不持久化密码', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetcher)
    await changePassword('old-password-123', 'new-password-456')
    const init = fetcher.mock.calls[0]?.[1] as RequestInit
    expect(init.body).toContain('"current_password"')
    expect(init.body).toContain('"new_password"')
  })

  it('业务请求拒绝跨源基址', () => {
    expect(() => new ApiClient({
      baseUrl: 'https://other.invalid',
      fetcher: vi.fn(),
    })).toThrow('TD-API-CONFIG-SAME-ORIGIN-001')
  })

  it('未认证响应清理界面身份', async () => {
    const auth = useAuthStore()
    auth.establish(parseIdentity({ ...identity, password_change_required: false }))
    const api = new ApiClient({
      baseUrl: window.location.origin,
      fetcher: vi.fn().mockResolvedValue(new Response(JSON.stringify({
        code: 'TD-AUTH-UNAUTHORIZED-001',
        message: '身份认证失败',
      }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      })),
      onAuthenticationFailure: auth.clear,
    })
    await expect(api.listDetections()).rejects.toBeDefined()
    expect(auth.authenticated).toBe(false)
  })
})
