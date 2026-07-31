import { ensureCsrf } from '@/auth/local-auth'

import { toApiError } from './errors'
import type { GeneratedApiClient, JsonObject } from './generated'

type WebConsoleOperation =
  | 'listDetections'
  | 'getDetection'
  | 'listReviewTasks'
  | 'getReviewWorkspace'
  | 'claimReviewTask'
  | 'releaseReviewTask'
  | 'submitReview'
  | 'createAnnotationUploadTicket'
  | 'completeReviewAnnotation'
  | 'createImageAccessTicket'
  | 'streamAuthorizedEvents'

export type WebConsoleGeneratedApiClient = Pick<
  GeneratedApiClient,
  WebConsoleOperation
>

export interface ApiClientOptions {
  readonly baseUrl: string
  readonly refreshProvider?: unknown
  readonly fetcher?: typeof fetch
  readonly requestIdFactory?: () => string
  readonly onAuthenticationFailure?: () => void
}

export class AuthenticationRefreshError extends Error {
  override readonly cause: unknown

  constructor(cause: unknown) {
    super(
      cause instanceof Error && cause.message.startsWith('TD-AUTH-')
        ? cause.message
        : 'TD-AUTH-REFRESH-001',
    )
    this.name = 'AuthenticationRefreshError'
    this.cause = cause
  }
}

interface OperationDefinition {
  readonly method: 'GET' | 'POST'
  readonly path: string
  readonly response: 'json' | 'event-stream'
}

interface OperationEnvelope {
  readonly path: JsonObject
  readonly query: JsonObject
  readonly headers: JsonObject
  readonly body: JsonObject | null
}

const OPERATIONS = {
  listDetections: {
    method: 'GET',
    path: '/api/v1/detections',
    response: 'json',
  },
  getDetection: {
    method: 'GET',
    path: '/api/v1/detections/{detection_task_id}',
    response: 'json',
  },
  listReviewTasks: {
    method: 'GET',
    path: '/api/v1/review-tasks',
    response: 'json',
  },
  getReviewWorkspace: {
    method: 'GET',
    path: '/api/v1/review-tasks/{review_task_id}',
    response: 'json',
  },
  claimReviewTask: {
    method: 'POST',
    path: '/api/v1/review-tasks/{review_task_id}/claim',
    response: 'json',
  },
  releaseReviewTask: {
    method: 'POST',
    path: '/api/v1/review-tasks/{review_task_id}/release',
    response: 'json',
  },
  submitReview: {
    method: 'POST',
    path: '/api/v1/review-tasks/{review_task_id}/submissions',
    response: 'json',
  },
  createAnnotationUploadTicket: {
    method: 'POST',
    path: '/api/v1/review-tasks/{review_task_id}/annotation-upload-ticket',
    response: 'json',
  },
  completeReviewAnnotation: {
    method: 'POST',
    path: '/api/v1/review-tasks/{review_task_id}/annotations/{image_id}/complete',
    response: 'json',
  },
  createImageAccessTicket: {
    method: 'POST',
    path: '/api/v1/images/{image_id}/access-ticket',
    response: 'json',
  },
  streamAuthorizedEvents: {
    method: 'GET',
    path: '/api/v1/events/stream',
    response: 'event-stream',
  },
} as const satisfies Record<WebConsoleOperation, OperationDefinition>

export class ApiClient implements WebConsoleGeneratedApiClient {
  private readonly baseUrl: string
  private readonly fetcher: typeof fetch
  private readonly requestIdFactory: () => string
  private readonly onAuthenticationFailure: () => void

  constructor(options: ApiClientOptions) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl)
    this.fetcher =
      options.fetcher ?? ((input, init) => window.fetch(input, init))
    this.requestIdFactory =
      options.requestIdFactory ?? (() => crypto.randomUUID())
    this.onAuthenticationFailure = options.onAuthenticationFailure ?? (() => undefined)
  }

  listDetections(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listDetections', request)
  }

  getDetection(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getDetection', request)
  }

  listReviewTasks(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listReviewTasks', request)
  }

  getReviewWorkspace(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getReviewWorkspace', request)
  }

  claimReviewTask(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('claimReviewTask', request)
  }

  releaseReviewTask(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('releaseReviewTask', request)
  }

  submitReview(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('submitReview', request)
  }

  createAnnotationUploadTicket(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('createAnnotationUploadTicket', request)
  }

  completeReviewAnnotation(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('completeReviewAnnotation', request)
  }

  createImageAccessTicket(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('createImageAccessTicket', request)
  }

  async streamAuthorizedEvents(request?: JsonObject): Promise<JsonObject> {
    const response = await this.openAuthorizedEventStream(request)
    const content = await response.text()
    return Object.freeze({ content })
  }

  async openAuthorizedEventStream(
    request?: JsonObject,
    signal?: AbortSignal,
  ): Promise<Response> {
    const response = await this.invokeResponse(
      'streamAuthorizedEvents',
      request,
      signal,
    )
    if (!response.ok) {
      const error = await toApiError(response)
      throw error
    }
    if (response.body === null) {
      throw new Error('TD-SSE-BODY-001')
    }
    return response
  }

  private async invokeJson(
    operation: Exclude<WebConsoleOperation, 'streamAuthorizedEvents'>,
    request?: JsonObject,
  ): Promise<JsonObject> {
    const response = await this.invokeResponse(operation, request)
    if (!response.ok) {
      const error = await toApiError(response)
      throw error
    }
    if (response.status === 204) {
      return Object.freeze({})
    }
    const value: unknown = await response.json()
    if (!isJsonObject(value)) {
      throw new Error('TD-API-RESPONSE-001')
    }
    return value
  }

  private invokeResponse(
    operation: WebConsoleOperation,
    request?: JsonObject,
    signal?: AbortSignal,
  ): Promise<Response> {
    const definition = OPERATIONS[operation]
    const envelope = parseEnvelope(request)
    const path = expandPath(definition.path, envelope.path)
    const url = appendQuery(this.resolvePath(path), envelope.query)
    const headers = operationHeaders(envelope.headers)
    headers.set(
      'Accept',
      definition.response === 'event-stream'
        ? 'text/event-stream'
        : 'application/json',
    )
    let body: string | undefined
    if (envelope.body !== null) {
      if (definition.method === 'GET') {
        throw new Error('TD-API-GET-BODY-001')
      }
      headers.set('Content-Type', 'application/json')
      body = JSON.stringify(envelope.body)
    }
    return this.fetchAuthenticated(url, {
      method: definition.method,
      credentials: 'same-origin',
      headers,
      ...(body === undefined ? {} : { body }),
      ...(signal === undefined ? {} : { signal }),
    })
  }

  private async fetchAuthenticated(
    url: string,
    init: RequestInit,
  ): Promise<Response> {
    const headers = this.authenticatedHeaders(init.headers)
    const method = (init.method ?? 'GET').toUpperCase()
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      headers.set('X-TD-CSRF', await ensureCsrf(this.fetcher))
      headers.set('Idempotency-Key', this.requestIdFactory())
    }
    const response = await this.fetcher(url, {
      ...init,
      credentials: 'same-origin',
      headers,
    })
    if (response.status === 401) {
      this.clearAuthentication()
    }
    return response
  }

  private clearAuthentication(): void {
    try {
      this.onAuthenticationFailure()
    } catch {
      // 会话已先清除；界面清理回调不得阻止安全失败。
    }
  }

  private authenticatedHeaders(additional?: HeadersInit): Headers {
    const headers = new Headers(additional)
    if (!headers.has('Accept')) {
      headers.set('Accept', 'application/json')
    }
    headers.set('X-Request-Id', this.requestIdFactory())
    return headers
  }

  private resolvePath(path: string): string {
    if (!path.startsWith('/')) {
      throw new Error('TD-API-PATH-001')
    }
    return `${this.baseUrl}${path}`
  }
}

function parseEnvelope(request?: JsonObject): OperationEnvelope {
  if (request === undefined) {
    return { path: {}, query: {}, headers: {}, body: null }
  }
  const allowed = new Set(['path', 'query', 'headers', 'body'])
  if (Object.keys(request).some((key) => !allowed.has(key))) {
    throw new Error('TD-API-REQUEST-ENVELOPE-001')
  }
  return {
    path: nestedObject(request.path, 'path'),
    query: nestedObject(request.query, 'query'),
    headers: nestedObject(request.headers, 'headers'),
    body:
      request.body === undefined || request.body === null
        ? null
        : nestedObject(request.body, 'body'),
  }
}

function normalizeBaseUrl(value: string): string {
  let url: URL
  try {
    url = new URL(value)
  } catch {
    throw new Error('TD-API-CONFIG-URL-001')
  }
  const localDevelopmentHost =
    url.hostname === 'localhost' || url.hostname === '127.0.0.1'
  const secureTransport =
    url.protocol === 'https:' ||
    (url.protocol === 'http:' && localDevelopmentHost)
  if (
    !secureTransport ||
    url.username.length > 0 ||
    url.password.length > 0 ||
    url.search.length > 0 ||
    url.hash.length > 0
  ) {
    throw new Error('TD-API-CONFIG-HTTPS-001')
  }
  if (url.origin !== window.location.origin) {
    throw new Error('TD-API-CONFIG-SAME-ORIGIN-001')
  }
  return url.toString().replace(/\/+$/, '')
}

function nestedObject(value: unknown, section: string): JsonObject {
  if (value === undefined) {
    return {}
  }
  if (!isJsonObject(value)) {
    throw new Error(`TD-API-REQUEST-${section.toUpperCase()}-001`)
  }
  return value
}

function expandPath(template: string, values: JsonObject): string {
  const used = new Set<string>()
  const path = template.replace(/\{([^}]+)\}/g, (_match, key: string) => {
    const value = values[key]
    if (!isScalar(value)) {
      throw new Error(`TD-API-PATH-PARAMETER-${key}`)
    }
    used.add(key)
    return encodeURIComponent(String(value))
  })
  if (Object.keys(values).some((key) => !used.has(key))) {
    throw new Error('TD-API-PATH-PARAMETER-UNUSED')
  }
  return path
}

function appendQuery(url: string, query: JsonObject): string {
  const target = new URL(url, window.location.origin)
  for (const [key, raw] of Object.entries(query)) {
    const values = Array.isArray(raw) ? raw : [raw]
    for (const value of values) {
      if (value === null || value === undefined) {
        continue
      }
      if (!isScalar(value)) {
        throw new Error(`TD-API-QUERY-PARAMETER-${key}`)
      }
      target.searchParams.append(key, String(value))
    }
  }
  return target.toString()
}

function operationHeaders(values: JsonObject): Headers {
  const headers = new Headers()
  const forbidden = new Set([
    'authorization',
    'cookie',
    'host',
    'content-length',
  ])
  for (const [key, value] of Object.entries(values)) {
    if (forbidden.has(key.toLowerCase())) {
      throw new Error(`TD-API-HEADER-FORBIDDEN-${key.toUpperCase()}`)
    }
    if (!isScalar(value)) {
      throw new Error(`TD-API-HEADER-${key}`)
    }
    headers.set(key, String(value))
  }
  return headers
}

function isScalar(value: unknown): value is string | number | boolean {
  return (
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  )
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
