import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { AuthenticatedEventStream } from '@/api/event-stream'
import { memorySession } from '@/stores/auth'

describe('认证服务器发送事件', () => {
  beforeEach(() => {
    memorySession.clear()
    memorySession.set({
      identity: {
        subject: 'quality-user',
        displayName: '质量负责人',
        roles: ['QUALITY_MANAGER'],
        permissions: ['quality:read'],
      },
      tokens: {
        accessToken: 'header-only-token',
        refreshToken: 'memory-only-refresh',
        expiresAtEpochMs: Date.now() + 60_000,
      },
    })
  })

  it('断流后自动重连并携带最后事件标识', async () => {
    let call = 0
    const controller = new AbortController()
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      call += 1
      expect(String(input)).toBe('https://api.invalid/api/v1/events/stream')
      expect(String(input)).not.toContain('header-only-token')
      const headers = new Headers(init?.headers)
      expect(headers.get('Authorization')).toBe('Bearer header-only-token')
      expect(headers.get('Last-Event-ID')).toBe(call === 1 ? null : 'event-1')
      return eventResponse(
        call === 1
          ? 'id: event-1\nevent: detection.updated\ndata: {"capture_id":"capture-1"}\n\n'
          : 'id: event-2\ndata: second\n\n',
      )
    })
    const stream = createStream(fetcher)
    const events: unknown[] = []

    await stream.connect((event) => {
      events.push(event)
      if (events.length === 2) {
        controller.abort()
      }
    }, controller.signal)

    expect(events).toHaveLength(2)
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(window.localStorage.length).toBe(0)
  })

  it('连接收到 401 时刷新令牌并重试同一事件操作', async () => {
    let call = 0
    const controller = new AbortController()
    const refresh = vi.fn(async () => ({
      accessToken: 'refreshed-token',
      refreshToken: 'next-refresh',
      expiresAtEpochMs: Date.now() + 60_000,
    }))
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      call += 1
      const token = new Headers(init?.headers).get('Authorization')
      if (call === 1) {
        expect(token).toBe('Bearer header-only-token')
        return new Response(null, { status: 401 })
      }
      expect(token).toBe('Bearer refreshed-token')
      return eventResponse('id: event-3\ndata: recovered\n\n')
    })
    const stream = createStream(fetcher, { refresh })

    await stream.connect(() => controller.abort(), controller.signal)

    expect(refresh).toHaveBeenCalledOnce()
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('事件流刷新失败时清除会话并停止重连', async () => {
    const fetcher = vi.fn(async () => new Response(null, { status: 401 }))
    const stream = createStream(fetcher, {
      refresh: vi.fn(async () => {
        throw new Error('身份服务不可达')
      }),
    })

    await expect(
      stream.connect(() => undefined, new AbortController().signal),
    ).rejects.toThrow('TD-AUTH-REFRESH-001')
    expect(memorySession.session).toBeNull()
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it('回放窗口失效时重查列表并清空最后事件标识', async () => {
    let call = 0
    const controller = new AbortController()
    const onReplayWindowExpired = vi.fn(async () => undefined)
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      call += 1
      const lastEventId = new Headers(init?.headers).get('Last-Event-ID')
      if (call === 1) {
        expect(lastEventId).toBeNull()
        return eventResponse('id: event-7\ndata: first\n\n')
      }
      if (call === 2) {
        expect(lastEventId).toBe('event-7')
        return Response.json(
          {
            code: 'TD-EVENT-REPLAY-WINDOW-EXPIRED',
            message: '回放窗口已过期',
            retryable: true,
          },
          { status: 410 },
        )
      }
      expect(lastEventId).toBeNull()
      return eventResponse('id: event-8\ndata: after-query\n\n')
    })
    const stream = createStream(fetcher, { onReplayWindowExpired })

    await stream.connect((event) => {
      if (event.id === 'event-8') {
        controller.abort()
      }
    }, controller.signal)

    expect(onReplayWindowExpired).toHaveBeenCalledOnce()
    expect(fetcher).toHaveBeenCalledTimes(3)
  })

  it('网络错误采用带上限的指数退避后继续连接', async () => {
    let call = 0
    const delays: number[] = []
    const controller = new AbortController()
    const fetcher = vi.fn(async () => {
      call += 1
      if (call === 1) {
        throw new TypeError('网络断开')
      }
      return eventResponse('data: ready\n\n')
    })
    const stream = createStream(fetcher, {
      retryPolicy: { initialDelayMs: 100, maxDelayMs: 400, jitterRatio: 0 },
      sleep: async (delay) => {
        delays.push(delay)
      },
    })

    await stream.connect(() => controller.abort(), controller.signal)

    expect(delays).toEqual([100])
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('拒绝非事件流媒体类型且不把协议错误当作可重连断网', async () => {
    const fetcher = vi.fn(async () =>
      Response.json({ message: '代理返回了普通 JSON' }, { status: 200 }),
    )
    const stream = createStream(fetcher)

    await expect(
      stream.connect(() => undefined, new AbortController().signal),
    ).rejects.toThrow('TD-SSE-CONTENT-TYPE-001')
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it.each([
    ['未分帧缓冲', `data: ${'x'.repeat(256 * 1_024 + 1)}`],
    ['单个完整事件', `data: ${'x'.repeat(256 * 1_024 + 1)}\n\n`],
  ])('%s 超过上限时显式失败', async (_caseName, body) => {
    const fetcher = vi.fn(async () => eventResponse(body))
    const stream = createStream(fetcher)

    await expect(
      stream.connect(() => undefined, new AbortController().signal),
    ).rejects.toThrow('TD-SSE-EVENT-TOO-LARGE-001')
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it('拒绝超过冻结请求头约束的事件标识', async () => {
    const fetcher = vi.fn(async () =>
      eventResponse(`id: ${'e'.repeat(129)}\ndata: private\n\n`),
    )
    const stream = createStream(fetcher)

    await expect(
      stream.connect(() => undefined, new AbortController().signal),
    ).rejects.toThrow('TD-SSE-EVENT-ID-001')
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it('把服务端 retry 0 提升到最小重连间隔', async () => {
    const delays: number[] = []
    const controller = new AbortController()
    const fetcher = vi.fn(async () => eventResponse('retry: 0\n\n'))
    const stream = createStream(fetcher, {
      sleep: async (delay) => {
        delays.push(delay)
        controller.abort()
      },
    })

    await stream.connect(() => undefined, controller.signal)

    expect(delays).toEqual([250])
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it('切换账号会终止旧事件流并在新会话清空事件游标', async () => {
    let call = 0
    let markOldEventSeen!: () => void
    const oldEventSeen = new Promise<void>((resolve) => {
      markOldEventSeen = resolve
    })
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      call += 1
      const lastEventId = new Headers(init?.headers).get('Last-Event-ID')
      if (call === 1) {
        expect(lastEventId).toBeNull()
        const encoder = new TextEncoder()
        return eventResponse(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(
                encoder.encode('id: user-a-event\ndata: private-a\n\n'),
              )
            },
          }),
        )
      }
      expect(lastEventId).toBeNull()
      return eventResponse('id: user-b-event\ndata: private-b\n\n')
    })
    const stream = createStream(fetcher)
    const firstController = new AbortController()
    const firstConnection = stream.connect((event) => {
      if (event.id === 'user-a-event') {
        markOldEventSeen()
      }
    }, firstController.signal)
    await oldEventSeen

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
    await expect(firstConnection).rejects.toThrow('TD-AUTH-SESSION-STALE-001')

    const secondController = new AbortController()
    await stream.connect((event) => {
      if (event.id === 'user-b-event') {
        secondController.abort()
      }
    }, secondController.signal)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
})

function eventResponse(body: BodyInit | null, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'text/event-stream; charset=utf-8')
  return new Response(body, { ...init, headers })
}

function createStream(
  fetcher: ReturnType<typeof vi.fn>,
  options: {
    readonly refresh?: () => Promise<{
      readonly accessToken: string
      readonly refreshToken?: string
      readonly expiresAtEpochMs: number
    }>
    readonly onReplayWindowExpired?: () => void | Promise<void>
    readonly retryPolicy?: {
      readonly initialDelayMs: number
      readonly maxDelayMs: number
      readonly jitterRatio: number
    }
    readonly sleep?: (delayMs: number, signal: AbortSignal) => Promise<void>
  } = {},
): AuthenticatedEventStream {
  const api = new ApiClient({
    baseUrl: 'https://api.invalid',
    refreshProvider: { refresh: options.refresh ?? vi.fn() },
    fetcher: fetcher as typeof fetch,
    requestIdFactory: () => 'request-stream',
  })
  return new AuthenticatedEventStream({
    api,
    onReplayWindowExpired:
      options.onReplayWindowExpired ?? vi.fn(async () => undefined),
    retryPolicy: options.retryPolicy,
    sleep: options.sleep ?? (async () => undefined),
    random: () => 0.5,
  })
}
