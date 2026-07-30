import { createPinia, setActivePinia } from 'pinia'
import type { RouteLocationNormalized } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import { createAuthorizationGuard } from '@/router/guard'
import { memorySession, useAuthStore } from '@/stores/auth'

function route(
  overrides: Partial<RouteLocationNormalized> & {
    meta: RouteLocationNormalized['meta']
  },
): RouteLocationNormalized {
  return {
    fullPath: '/quality',
    hash: '',
    matched: [],
    name: 'quality',
    params: {},
    path: '/quality',
    query: {},
    redirectedFrom: undefined,
    href: '/quality',
    ...overrides,
    meta: overrides.meta,
  } as RouteLocationNormalized
}

describe('路由认证与权限守卫', () => {
  const pinia = createPinia()

  beforeEach(() => {
    setActivePinia(pinia)
    useAuthStore(pinia).clear()
    memorySession.clear()
  })

  it('未登录用户访问受保护路由时返回安全登录重定向', () => {
    const result = createAuthorizationGuard(pinia)(
      route({
        fullPath: '/quality?station=one',
        meta: { requiresAuth: true, permissions: ['quality:read'] },
      }),
    )
    expect(result).toEqual({
      name: 'login',
      query: { redirect: '/quality?station=one' },
    })
  })

  it('OIDC 回调路由无需预先登录即可完成会话引导', () => {
    const result = createAuthorizationGuard(pinia)(
      route({
        name: 'oidc-callback',
        path: '/auth/callback',
        fullPath: '/auth/callback?code=one&state=two',
        meta: { requiresAuth: false, standalone: true },
      }),
    )
    expect(result).toBe(true)
  })

  it('登录但无权限时拒绝直接路由访问', () => {
    useAuthStore(pinia).establish({
      identity: {
        subject: 'operator',
        displayName: '操作员',
        roles: ['OPERATOR'],
        permissions: ['detection:read'],
      },
      tokens: {
        accessToken: 'token',
        expiresAtEpochMs: Date.now() + 60_000,
      },
    })
    const result = createAuthorizationGuard(pinia)(
      route({
        meta: { requiresAuth: true, permissions: ['quality:read'] },
      }),
    )
    expect(result).toEqual({ name: 'unauthorized' })
  })

  it('具备全部权限时放行', () => {
    useAuthStore(pinia).establish({
      identity: {
        subject: 'quality',
        displayName: '质量负责人',
        roles: ['QUALITY_MANAGER'],
        permissions: ['quality:read', 'detection:read'],
      },
      tokens: {
        accessToken: 'token',
        expiresAtEpochMs: Date.now() + 60_000,
      },
    })
    const result = createAuthorizationGuard(pinia)(
      route({
        meta: {
          requiresAuth: true,
          permissions: ['quality:read', 'detection:read'],
        },
      }),
    )
    expect(result).toBe(true)
  })
})
