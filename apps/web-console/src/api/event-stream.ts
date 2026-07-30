import { ApiClient, AuthenticationRefreshError } from './client'
import { ApiError } from './errors'

export interface ServerEvent<T = unknown> {
  readonly id: string | null
  readonly event: string
  readonly data: T
}

export interface EventStreamRetryPolicy {
  readonly initialDelayMs: number
  readonly maxDelayMs: number
  readonly jitterRatio: number
}

export interface EventStreamOptions {
  readonly api: ApiClient
  readonly onReplayWindowExpired: () => void | Promise<void>
  readonly retryPolicy?: Partial<EventStreamRetryPolicy>
  readonly sleep?: (delayMs: number, signal: AbortSignal) => Promise<void>
  readonly random?: () => number
  readonly isReplayWindowExpired?: (error: unknown) => boolean
}

interface ParsedBlock {
  readonly event: ServerEvent | null
  readonly retryMs: number | null
}

class EventCallbackError extends Error {
  constructor(override readonly cause: unknown) {
    super('TD-SSE-CALLBACK-001')
  }
}

const DEFAULT_RETRY_POLICY: EventStreamRetryPolicy = {
  initialDelayMs: 1_000,
  maxDelayMs: 30_000,
  jitterRatio: 0.2,
}

const MAX_EVENT_CHARACTERS = 256 * 1_024
const MAX_EVENT_ID_CHARACTERS = 128
const MIN_SERVER_RETRY_MS = 250

/**
 * 使用同源会话读取服务器发送事件；断线后自动携带
 * `Last-Event-ID` 重连，有限回放窗口失效时先通知调用方重新查询列表。
 */
export class AuthenticatedEventStream {
  private readonly api: ApiClient
  private readonly onReplayWindowExpired: () => void | Promise<void>
  private readonly retryPolicy: EventStreamRetryPolicy
  private readonly sleep: (delayMs: number, signal: AbortSignal) => Promise<void>
  private readonly random: () => number
  private readonly isReplayWindowExpired: (error: unknown) => boolean
  private lastEventId: string | null = null

  constructor(options: EventStreamOptions) {
    this.api = options.api
    this.onReplayWindowExpired = options.onReplayWindowExpired
    this.retryPolicy = {
      ...DEFAULT_RETRY_POLICY,
      ...options.retryPolicy,
    }
    validateRetryPolicy(this.retryPolicy)
    this.sleep = options.sleep ?? abortableSleep
    this.random = options.random ?? Math.random
    this.isReplayWindowExpired =
      options.isReplayWindowExpired ?? defaultReplayWindowExpired
  }

  async connect(
    onEvent: (event: ServerEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const activeSignal = signal
    {
      let reconnectAttempt = 0
      let serverRetryMs: number | null = null
      while (!activeSignal.aborted) {
        try {
          const request =
            this.lastEventId === null
              ? undefined
              : { headers: { 'Last-Event-ID': this.lastEventId } }
          const response = await this.api.openAuthorizedEventStream(
            request,
            activeSignal,
          )
          const result = await consumeResponse(
            response,
            (event) => {
              if (event.id !== null) {
                this.lastEventId = event.id.length === 0 ? null : event.id
              }
              try {
                onEvent(event)
              } catch (error) {
                throw new EventCallbackError(error)
              }
            },
            activeSignal,
          )
          serverRetryMs =
            result.retryMs === null
              ? serverRetryMs
              : Math.max(
                  1,
                  Math.min(
                    this.retryPolicy.maxDelayMs,
                    Math.max(MIN_SERVER_RETRY_MS, result.retryMs),
                  ),
                )
          reconnectAttempt = result.receivedEvent ? 0 : reconnectAttempt + 1
        } catch (error) {
          if (signal.aborted) {
            return
          }
          if (error instanceof EventCallbackError) {
            throw error.cause
          }
          if (isAuthenticationFailure(error)) {
            throw error
          }
          if (isProtocolFailure(error)) {
            throw error
          } else if (this.isReplayWindowExpired(error)) {
            this.lastEventId = null
            reconnectAttempt = 0
            await this.onReplayWindowExpired()
          } else {
            reconnectAttempt += 1
          }
        }
        if (signal.aborted) {
          return
        }
        const delay =
          serverRetryMs ?? this.retryDelay(Math.max(0, reconnectAttempt - 1))
        await this.sleep(delay, activeSignal)
      }
    }
  }

  private retryDelay(attempt: number): number {
    const base = Math.min(
      this.retryPolicy.maxDelayMs,
      this.retryPolicy.initialDelayMs * 2 ** attempt,
    )
    const jitter =
      base * this.retryPolicy.jitterRatio * (this.random() * 2 - 1)
    return Math.max(1, Math.round(base + jitter))
  }
}

async function consumeResponse(
  response: Response,
  onEvent: (event: ServerEvent) => void,
  signal: AbortSignal,
): Promise<{ readonly receivedEvent: boolean; readonly retryMs: number | null }> {
  assertEventStreamContentType(response)
  const reader = response.body?.getReader()
  if (reader === undefined) {
    throw new Error('TD-SSE-BODY-001')
  }
  const decoder = new TextDecoder()
  let buffer = ''
  let receivedEvent = false
  let retryMs: number | null = null
  const cancelOnAbort = (): void => {
    void reader.cancel().catch(() => undefined)
  }
  if (signal.aborted) {
    cancelOnAbort()
  } else {
    signal.addEventListener('abort', cancelOnAbort, { once: true })
  }
  try {
    while (!signal.aborted) {
      const item = await reader.read()
      if (item.done) {
        break
      }
      buffer += decoder.decode(item.value, { stream: true })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() ?? ''
      if (buffer.length > MAX_EVENT_CHARACTERS) {
        throw new Error('TD-SSE-EVENT-TOO-LARGE-001')
      }
      for (const block of blocks) {
        if (block.length > MAX_EVENT_CHARACTERS) {
          throw new Error('TD-SSE-EVENT-TOO-LARGE-001')
        }
        const parsed = parseEvent(block)
        retryMs = parsed.retryMs ?? retryMs
        if (parsed.event !== null) {
          receivedEvent = true
          onEvent(parsed.event)
        }
        if (signal.aborted) {
          break
        }
      }
    }
  } finally {
    signal.removeEventListener('abort', cancelOnAbort)
    reader.releaseLock()
  }
  return { receivedEvent, retryMs }
}

function parseEvent(block: string): ParsedBlock {
  let id: string | null = null
  let event = 'message'
  let retryMs: number | null = null
  const data: string[] = []
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith(':')) {
      continue
    }
    const separator = line.indexOf(':')
    const field = separator >= 0 ? line.slice(0, separator) : line
    const rawValue = separator >= 0 ? line.slice(separator + 1) : ''
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue
    if (field === 'id' && !value.includes('\0')) {
      if (value.length > MAX_EVENT_ID_CHARACTERS) {
        throw new Error('TD-SSE-EVENT-ID-001')
      }
      id = value
    } else if (field === 'event') {
      event = value
    } else if (field === 'retry' && /^\d+$/.test(value)) {
      const parsedRetry = Number(value)
      retryMs = Number.isSafeInteger(parsedRetry) ? parsedRetry : retryMs
    } else if (field === 'data') {
      data.push(value)
    }
  }
  if (data.length === 0) {
    return { event: null, retryMs }
  }
  const joined = data.join('\n')
  let decoded: unknown = joined
  try {
    decoded = JSON.parse(joined)
  } catch {
    // 文本事件保持原样；不执行动态代码。
  }
  return { event: { id, event, data: decoded }, retryMs }
}

function validateRetryPolicy(policy: EventStreamRetryPolicy): void {
  if (
    !Number.isFinite(policy.initialDelayMs) ||
    policy.initialDelayMs <= 0 ||
    !Number.isFinite(policy.maxDelayMs) ||
    policy.maxDelayMs < policy.initialDelayMs ||
    !Number.isFinite(policy.jitterRatio) ||
    policy.jitterRatio < 0 ||
    policy.jitterRatio > 1
  ) {
    throw new Error('TD-SSE-RETRY-POLICY-001')
  }
}

function assertEventStreamContentType(response: Response): void {
  const contentType = response.headers.get('Content-Type')
  const mediaType = contentType?.split(';', 1)[0]?.trim().toLowerCase()
  if (mediaType !== 'text/event-stream') {
    throw new Error('TD-SSE-CONTENT-TYPE-001')
  }
}

function defaultReplayWindowExpired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 410
}

function isAuthenticationFailure(error: unknown): boolean {
  return (
    (error instanceof ApiError && (error.status === 401 || error.status === 403)) ||
    error instanceof AuthenticationRefreshError ||
    (error instanceof Error && error.message.startsWith('TD-AUTH-'))
  )
}

function isProtocolFailure(error: unknown): boolean {
  return (
    error instanceof Error &&
    (error.message === 'TD-SSE-BODY-001' ||
      error.message === 'TD-SSE-CONTENT-TYPE-001' ||
      error.message === 'TD-SSE-EVENT-ID-001' ||
      error.message === 'TD-SSE-EVENT-TOO-LARGE-001')
  )
}

function abortableSleep(delayMs: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted || delayMs === 0) {
    return Promise.resolve()
  }
  return new Promise((resolve) => {
    const timeout = window.setTimeout(finish, delayMs)
    signal.addEventListener('abort', finish, { once: true })
    function finish(): void {
      window.clearTimeout(timeout)
      signal.removeEventListener('abort', finish)
      resolve()
    }
  })
}

function linkAbortSignals(
  ...signals: readonly AbortSignal[]
): { readonly signal: AbortSignal; readonly dispose: () => void } {
  const controller = new AbortController()
  const abort = (): void => {
    controller.abort()
  }
  for (const signal of signals) {
    if (signal.aborted) {
      controller.abort()
    } else {
      signal.addEventListener('abort', abort, { once: true })
    }
  }
  return {
    signal: controller.signal,
    dispose: () => {
      for (const signal of signals) {
        signal.removeEventListener('abort', abort)
      }
    },
  }
}
