import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiClient,
  type WebConsoleGeneratedApiClient,
} from '@/api/client'
import { EphemeralUrlRegistry } from '@/api/ephemeral-urls'
import { memorySession } from '@/stores/auth'
import type { AuthTokens } from '@/auth/types'

describe('生成契约统一请求层', () => {
  beforeEach(() => {
    memorySession.clear()
    memorySession.set({
      identity: {
        subject: 'user',
        displayName: '用户',
        roles: [],
        permissions: [],
      },
      tokens: {
        accessToken: 'first-token',
        refreshToken: 'refresh-token',
        expiresAtEpochMs: Date.now() + 60_000,
      },
    })
  })

  it('通过生成客户端操作注入令牌、请求标识和查询参数', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe(
        'https://api.invalid/api/v1/detections?cursor=next&page_size=20',
      )
      const headers = new Headers(init?.headers)
      expect(headers.get('Authorization')).toBe('Bearer first-token')
      expect(headers.get('X-Request-Id')).toBe('request-1')
      return Response.json({ items: [] })
    })
    const client = createClient(fetcher)
    const generated: WebConsoleGeneratedApiClient = client

    await expect(
      generated.listDetections({
        query: { cursor: 'next', page_size: 20 },
      }),
    ).resolves.toEqual({ items: [] })
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it('拒绝可能泄露用户令牌的非安全业务接口地址', () => {
    const options = {
      refreshProvider: { refresh: vi.fn() },
      fetcher: vi.fn() as unknown as typeof fetch,
    }
    expect(
      () => new ApiClient({ ...options, baseUrl: 'http://api.invalid' }),
    ).toThrow('TD-API-CONFIG-HTTPS-001')
    expect(
      () =>
        new ApiClient({
          ...options,
          baseUrl: 'https://user:password@api.invalid',
        }),
    ).toThrow('TD-API-CONFIG-HTTPS-001')
    expect(
      () =>
        new ApiClient({
          ...options,
          baseUrl: 'https://api.invalid?redirect=untrusted',
        }),
    ).toThrow('TD-API-CONFIG-HTTPS-001')
    expect(
      () => new ApiClient({ ...options, baseUrl: 'http://localhost:8080' }),
    ).not.toThrow()
  })

  it('冻结消费者清单中的八个操作均映射到实际请求', async () => {
    const calls: Array<{
      readonly url: string
      readonly method: string
      readonly headers: Headers
      readonly body: string | null
    }> = []
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        method: init?.method ?? 'GET',
        headers: new Headers(init?.headers),
        body: typeof init?.body === 'string' ? init.body : null,
      })
      return calls.length === 8
        ? new Response('id: one\ndata: ready\n\n', { status: 200 })
        : Response.json({ ok: true })
    })
    const client = createClient(fetcher)

    await client.listDetections({ query: { page_size: 5 } })
    await client.getDetection({ path: { detection_task_id: 'detection/one' } })
    await client.listReviewTasks({ query: { status: 'PENDING' } })
    await client.claimReviewTask(actionRequest('review-1', '领取任务'))
    await client.releaseReviewTask(actionRequest('review-1', '释放任务'))
    await client.submitReview({
      path: { review_task_id: 'review-1' },
      headers: { 'Idempotency-Key': 'submit-0001', 'If-Match': '"3"' },
      body: { decision: 'CONFIRMED', reason: '证据完整' },
    })
    await client.createImageAccessTicket({
      path: { image_id: 'image-1' },
      headers: { 'Idempotency-Key': 'ticket-0001' },
      body: { purpose: 'DETAIL_VIEW' },
    })
    await expect(client.streamAuthorizedEvents()).resolves.toEqual({
      content: 'id: one\ndata: ready\n\n',
    })

    expect(calls.map((call) => [call.method, new URL(call.url).pathname])).toEqual([
      ['GET', '/api/v1/detections'],
      ['GET', '/api/v1/detections/detection%2Fone'],
      ['GET', '/api/v1/review-tasks'],
      ['POST', '/api/v1/review-tasks/review-1/claim'],
      ['POST', '/api/v1/review-tasks/review-1/release'],
      ['POST', '/api/v1/review-tasks/review-1/submissions'],
      ['POST', '/api/v1/images/image-1/access-ticket'],
      ['GET', '/api/v1/events/stream'],
    ])
    expect(calls[3]?.headers.get('Idempotency-Key')).toBe('action-0001')
    expect(calls[3]?.headers.get('If-Match')).toBe('"2"')
    expect(JSON.parse(calls[5]?.body ?? '{}')).toEqual({
      decision: 'CONFIRMED',
      reason: '证据完整',
    })
    expect(calls[7]?.headers.get('Accept')).toBe('text/event-stream')
  })

  it('401 时只刷新一次并用新令牌重试', async () => {
    let call = 0
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      call += 1
      const token = new Headers(init?.headers).get('Authorization')
      if (call === 1) {
        expect(token).toBe('Bearer first-token')
        return new Response(null, { status: 401 })
      }
      expect(token).toBe('Bearer refreshed-token')
      return Response.json({ ok: true })
    })
    const refresh = vi.fn(async () => ({
      accessToken: 'refreshed-token',
      refreshToken: 'next-refresh',
      expiresAtEpochMs: Date.now() + 60_000,
    }))
    const client = createClient(fetcher, { refresh })

    await expect(client.listDetections()).resolves.toEqual({ ok: true })
    expect(refresh).toHaveBeenCalledOnce()
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('刷新失败时清除内存会话和身份状态', async () => {
    const clearIdentity = vi.fn()
    const client = createClient(
      vi.fn(async () => new Response(null, { status: 401 })),
      {
        refresh: vi.fn(async () => {
          throw new Error('TD-AUTH-TOKEN-503')
        }),
        onAuthenticationFailure: clearIdentity,
      },
    )

    await expect(client.listDetections()).rejects.toThrow('TD-AUTH-TOKEN-503')
    expect(memorySession.session).toBeNull()
    expect(clearIdentity).toHaveBeenCalledOnce()
  })

  it('旧刷新失效时拒绝原请求但不清除后来建立的会话', async () => {
    const refreshResult = deferred<AuthTokens>()
    let signalRefreshStarted!: () => void
    const refreshStarted = new Promise<void>((resolve) => {
      signalRefreshStarted = resolve
    })
    const onAuthenticationFailure = vi.fn()
    const client = createClient(
      vi.fn(async () => new Response(null, { status: 401 })),
      {
        refresh: vi.fn(() => {
          signalRefreshStarted()
          return refreshResult.promise
        }),
        onAuthenticationFailure,
      },
    )

    const request = client.listDetections()
    await refreshStarted
    memorySession.clear()
    memorySession.set({
      identity: {
        subject: 'second-user',
        displayName: '第二位用户',
        roles: ['REVIEWER'],
        permissions: ['review:read'],
      },
      tokens: {
        accessToken: 'second-user-access',
        refreshToken: 'second-user-refresh',
        expiresAtEpochMs: Date.now() + 60_000,
      },
    })
    refreshResult.resolve({
      accessToken: 'stale-user-access',
      refreshToken: 'stale-user-refresh',
      expiresAtEpochMs: Date.now() + 60_000,
    })

    await expect(request).rejects.toThrow('TD-AUTH-SESSION-STALE-001')
    expect(memorySession.session?.identity.subject).toBe('second-user')
    expect(memorySession.accessToken).toBe('second-user-access')
    expect(onAuthenticationFailure).not.toHaveBeenCalled()
  })

  it('请求等待期间切换账号后不交付旧响应或以新令牌重放', async () => {
    const responseResult = deferred<Response>()
    const refresh = vi.fn(async () => ({
      accessToken: 'unexpected-refresh',
      expiresAtEpochMs: Date.now() + 60_000,
    }))
    const fetcher = vi.fn(() => responseResult.promise)
    const client = createClient(fetcher, { refresh })
    const request = client.listDetections()

    memorySession.clear()
    memorySession.set({
      identity: {
        subject: 'second-user',
        displayName: '第二位用户',
        roles: ['REVIEWER'],
        permissions: ['review:read'],
      },
      tokens: {
        accessToken: 'second-user-access',
        refreshToken: 'second-user-refresh',
        expiresAtEpochMs: Date.now() + 60_000,
      },
    })
    responseResult.resolve(new Response(null, { status: 401 }))

    await expect(request).rejects.toThrow('TD-AUTH-SESSION-STALE-001')
    expect(fetcher).toHaveBeenCalledOnce()
    expect(refresh).not.toHaveBeenCalled()
    expect(memorySession.session?.identity.subject).toBe('second-user')
    expect(memorySession.accessToken).toBe('second-user-access')
  })

  it('错误码按结构处理且拒绝绕过传输信封或覆盖认证头', async () => {
    const client = createClient(
      vi.fn(async () =>
        Response.json(
          {
            code: 'TD-API-CONFLICT-001',
            message: '幂等内容不一致',
            request_id: 'request',
            trace_id: 'a'.repeat(32),
            retryable: false,
            details: [{ field: 'capture_id', reason: 'DIGEST_MISMATCH' }],
          },
          { status: 409 },
        ),
      ),
    )

    await expect(client.listDetections()).rejects.toMatchObject({
      code: 'TD-API-CONFLICT-001',
      retryable: false,
      status: 409,
    })
    await expect(
      client.getDetection({ detection_task_id: 'bad' }),
    ).rejects.toThrow('TD-API-REQUEST-ENVELOPE-001')
    await expect(
      client.listDetections({ headers: { Authorization: 'Bearer bad' } }),
    ).rejects.toThrow('TD-API-HEADER-FORBIDDEN-AUTHORIZATION')
  })
})

describe('短时签名地址', () => {
  it('仅保存在内存且到期自动失效', () => {
    const registry = new EphemeralUrlRegistry()
    registry.put(
      'image-1',
      {
        url: 'https://storage.invalid/image?signature=temporary',
        expiresAtEpochMs: 1_300,
      },
      1_000,
    )
    expect(registry.get('image-1', 1_299)).toContain('temporary')
    expect(registry.get('image-1', 1_300)).toBeNull()
    expect(window.localStorage.length).toBe(0)
  })

  it('拒绝超长和非安全票据', () => {
    const registry = new EphemeralUrlRegistry()
    expect(() =>
      registry.put(
        'image',
        {
          url: 'http://storage.invalid/image',
          expiresAtEpochMs: 2_000,
        },
        1_000,
      ),
    ).toThrow('TD-STORAGE-TICKET-INSECURE')
    expect(() =>
      registry.put(
        'image',
        {
          url: 'ftp://localhost/image',
          expiresAtEpochMs: 2_000,
        },
        1_000,
      ),
    ).toThrow('TD-STORAGE-TICKET-INSECURE')
    expect(() =>
      registry.put(
        'image',
        {
          url: 'https://user:password@storage.invalid/image',
          expiresAtEpochMs: 2_000,
        },
        1_000,
      ),
    ).toThrow('TD-STORAGE-TICKET-INSECURE')
    expect(() =>
      registry.put(
        'image',
        {
          url: 'https://storage.invalid/image',
          expiresAtEpochMs: 1_000 + 16 * 60_000,
        },
        1_000,
      ),
    ).toThrow('TD-STORAGE-TICKET-TTL')
  })
})

function actionRequest(reviewTaskId: string, reason: string) {
  return {
    path: { review_task_id: reviewTaskId },
    headers: { 'Idempotency-Key': 'action-0001', 'If-Match': '"2"' },
    body: { reason },
  }
}

function createClient(
  fetcher: ReturnType<typeof vi.fn>,
  options: {
    readonly refresh?: () => Promise<{
      readonly accessToken: string
      readonly refreshToken?: string
      readonly expiresAtEpochMs: number
    }>
    readonly onAuthenticationFailure?: () => void
  } = {},
): ApiClient {
  return new ApiClient({
    baseUrl: 'https://api.invalid',
    refreshProvider: { refresh: options.refresh ?? vi.fn() },
    fetcher: fetcher as typeof fetch,
    requestIdFactory: () => 'request-1',
    onAuthenticationFailure: options.onAuthenticationFailure,
  })
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
