import { ensureCsrf } from '@/auth/local-auth'

import { toApiError } from './errors'
import type { JsonObject } from './generated'
import type { ApiClientV2 } from '@contracts/v2/client'

type WebConsoleOperation =
  | 'getSystemOverview'
  | 'listAuditRecords'
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
  | 'listDatasets'
  | 'createDataset'
  | 'listDatasetVersionCatalog'
  | 'createDatasetVersion'
  | 'listDatasetVersions'
  | 'getDatasetVersion'
  | 'diffDatasetVersions'
  | 'listDatasetCandidateManifests'
  | 'approveDatasetCandidateManifest'
  | 'approveDatasetVersion'
  | 'createTrainingRun'
  | 'listTrainingRuns'
  | 'getTrainingRun'
  | 'listModels'
  | 'createModel'
  | 'listModelVersions'
  | 'getModelVersion'
  | 'registerModelVersion'
  | 'submitModelValidationDecision'
  | 'createModelDeployment'
  | 'listModelDeployments'
  | 'getModelDeployment'
  | 'approveModelDeployment'
  | 'rollbackModelDeployment'
  | 'getQualityMetrics'
  | 'getManualDetectionCapabilitiesV2'
  | 'listDetectionBatchesV2'
  | 'createDetectionBatchV2'
  | 'getDetectionBatchV2'
  | 'addDetectionBatchItemV2'
  | 'getDetectionBatchItemV2'
  | 'deleteDetectionBatchItemV2'
  | 'completeDetectionBatchItemUploadV2'
  | 'renewDetectionBatchItemUploadV2'
  | 'submitDetectionBatchV2'
  | 'putQuickReviewV2'

type ManualDetectionApiV2 = Pick<ApiClientV2,
  | 'getManualDetectionCapabilitiesV2'
  | 'listDetectionBatchesV2'
  | 'createDetectionBatchV2'
  | 'getDetectionBatchV2'
  | 'addDetectionBatchItemV2'
  | 'getDetectionBatchItemV2'
  | 'deleteDetectionBatchItemV2'
  | 'completeDetectionBatchItemUploadV2'
  | 'renewDetectionBatchItemUploadV2'
  | 'submitDetectionBatchV2'
  | 'putQuickReviewV2'
>

export type WebConsoleGeneratedApiClient = ApiClient

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
  readonly method: 'GET' | 'POST' | 'PUT' | 'DELETE'
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
  getSystemOverview: {
    method: 'GET',
    path: '/api/v1/dashboard/overview',
    response: 'json',
  },
  listAuditRecords: {
    method: 'GET',
    path: '/api/v1/audit-records',
    response: 'json',
  },
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
  listDatasets: {
    method: 'GET',
    path: '/api/v1/datasets',
    response: 'json',
  },
  createDataset: {
    method: 'POST',
    path: '/api/v1/datasets',
    response: 'json',
  },
  listDatasetVersionCatalog: {
    method: 'GET',
    path: '/api/v1/dataset-versions',
    response: 'json',
  },
  createDatasetVersion: {
    method: 'POST',
    path: '/api/v1/dataset-versions',
    response: 'json',
  },
  listDatasetVersions: {
    method: 'GET',
    path: '/api/v1/datasets/{dataset_id}/versions',
    response: 'json',
  },
  getDatasetVersion: {
    method: 'GET',
    path: '/api/v1/dataset-versions/{dataset_version_id}',
    response: 'json',
  },
  diffDatasetVersions: {
    method: 'GET',
    path: '/api/v1/dataset-versions/diff',
    response: 'json',
  },
  listDatasetCandidateManifests: {
    method: 'GET',
    path: '/api/v1/dataset-candidate-manifests',
    response: 'json',
  },
  approveDatasetCandidateManifest: {
    method: 'POST',
    path: '/api/v1/dataset-candidate-manifests/{candidate_manifest_id}/approval',
    response: 'json',
  },
  approveDatasetVersion: {
    method: 'POST',
    path: '/api/v1/dataset-versions/{dataset_version_id}/approval',
    response: 'json',
  },
  createTrainingRun: {
    method: 'POST',
    path: '/api/v1/training-runs',
    response: 'json',
  },
  listTrainingRuns: {
    method: 'GET',
    path: '/api/v1/training-runs',
    response: 'json',
  },
  getTrainingRun: {
    method: 'GET',
    path: '/api/v1/training-runs/{training_run_id}',
    response: 'json',
  },
  listModels: {
    method: 'GET',
    path: '/api/v1/models',
    response: 'json',
  },
  createModel: {
    method: 'POST',
    path: '/api/v1/models',
    response: 'json',
  },
  listModelVersions: {
    method: 'GET',
    path: '/api/v1/model-versions',
    response: 'json',
  },
  getModelVersion: {
    method: 'GET',
    path: '/api/v1/model-versions/{model_version_id}',
    response: 'json',
  },
  registerModelVersion: {
    method: 'POST',
    path: '/api/v1/model-versions',
    response: 'json',
  },
  submitModelValidationDecision: {
    method: 'POST',
    path: '/api/v1/model-versions/{model_version_id}/validation-decisions',
    response: 'json',
  },
  createModelDeployment: {
    method: 'POST',
    path: '/api/v1/model-deployments',
    response: 'json',
  },
  listModelDeployments: {
    method: 'GET',
    path: '/api/v1/model-deployments',
    response: 'json',
  },
  getModelDeployment: {
    method: 'GET',
    path: '/api/v1/model-deployments/{model_deployment_id}',
    response: 'json',
  },
  approveModelDeployment: {
    method: 'POST',
    path: '/api/v1/model-deployments/{model_deployment_id}/approvals',
    response: 'json',
  },
  rollbackModelDeployment: {
    method: 'POST',
    path: '/api/v1/model-deployments/{model_deployment_id}/rollback',
    response: 'json',
  },
  getQualityMetrics: {
    method: 'GET',
    path: '/api/v1/quality/metrics',
    response: 'json',
  },
  getManualDetectionCapabilitiesV2: {
    method: 'GET', path: '/api/v2/capabilities/manual-detection', response: 'json',
  },
  listDetectionBatchesV2: {
    method: 'GET', path: '/api/v2/detection-batches', response: 'json',
  },
  createDetectionBatchV2: {
    method: 'POST', path: '/api/v2/detection-batches', response: 'json',
  },
  getDetectionBatchV2: {
    method: 'GET', path: '/api/v2/detection-batches/{batch_id}', response: 'json',
  },
  addDetectionBatchItemV2: {
    method: 'POST', path: '/api/v2/detection-batches/{batch_id}/items', response: 'json',
  },
  getDetectionBatchItemV2: {
    method: 'GET', path: '/api/v2/detection-batches/{batch_id}/items/{item_id}', response: 'json',
  },
  deleteDetectionBatchItemV2: {
    method: 'DELETE', path: '/api/v2/detection-batches/{batch_id}/items/{item_id}', response: 'json',
  },
  completeDetectionBatchItemUploadV2: {
    method: 'POST', path: '/api/v2/detection-batches/{batch_id}/items/{item_id}/complete', response: 'json',
  },
  renewDetectionBatchItemUploadV2: {
    method: 'POST', path: '/api/v2/detection-batches/{batch_id}/items/{item_id}/renew', response: 'json',
  },
  submitDetectionBatchV2: {
    method: 'POST', path: '/api/v2/detection-batches/{batch_id}/submit', response: 'json',
  },
  putQuickReviewV2: {
    method: 'PUT', path: '/api/v2/detection-batches/{batch_id}/items/{item_id}/quick-review', response: 'json',
  },
} as const satisfies Record<WebConsoleOperation, OperationDefinition>

export class ApiClient implements ManualDetectionApiV2 {
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

  getSystemOverview(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getSystemOverview', request)
  }

  listAuditRecords(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listAuditRecords', request)
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

  listDatasets(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listDatasets', request)
  }

  createDataset(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('createDataset', request)
  }

  listDatasetVersionCatalog(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listDatasetVersionCatalog', request)
  }

  createDatasetVersion(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('createDatasetVersion', request)
  }

  listDatasetVersions(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listDatasetVersions', request)
  }

  getDatasetVersion(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getDatasetVersion', request)
  }

  diffDatasetVersions(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('diffDatasetVersions', request)
  }

  listDatasetCandidateManifests(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listDatasetCandidateManifests', request)
  }

  approveDatasetCandidateManifest(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('approveDatasetCandidateManifest', request)
  }

  approveDatasetVersion(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('approveDatasetVersion', request)
  }

  createTrainingRun(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('createTrainingRun', request)
  }

  listTrainingRuns(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listTrainingRuns', request)
  }

  getTrainingRun(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getTrainingRun', request)
  }

  listModels(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listModels', request)
  }

  createModel(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('createModel', request)
  }

  listModelVersions(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listModelVersions', request)
  }

  getModelVersion(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getModelVersion', request)
  }

  registerModelVersion(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('registerModelVersion', request)
  }

  submitModelValidationDecision(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('submitModelValidationDecision', request)
  }

  createModelDeployment(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('createModelDeployment', request)
  }

  listModelDeployments(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listModelDeployments', request)
  }

  getModelDeployment(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getModelDeployment', request)
  }

  approveModelDeployment(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('approveModelDeployment', request)
  }

  rollbackModelDeployment(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('rollbackModelDeployment', request)
  }

  getQualityMetrics(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getQualityMetrics', request)
  }

  getManualDetectionCapabilitiesV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getManualDetectionCapabilitiesV2', request)
  }

  listDetectionBatchesV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('listDetectionBatchesV2', request)
  }

  createDetectionBatchV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('createDetectionBatchV2', request)
  }

  getDetectionBatchV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getDetectionBatchV2', request)
  }

  addDetectionBatchItemV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('addDetectionBatchItemV2', request)
  }

  getDetectionBatchItemV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('getDetectionBatchItemV2', request)
  }

  deleteDetectionBatchItemV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('deleteDetectionBatchItemV2', request)
  }

  completeDetectionBatchItemUploadV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('completeDetectionBatchItemUploadV2', request)
  }

  renewDetectionBatchItemUploadV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('renewDetectionBatchItemUploadV2', request)
  }

  submitDetectionBatchV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('submitDetectionBatchV2', request)
  }

  putQuickReviewV2(request?: JsonObject): Promise<JsonObject> {
    return this.invokeJson('putQuickReviewV2', request)
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
      if (!headers.has('Idempotency-Key')) {
        headers.set('Idempotency-Key', this.requestIdFactory())
      }
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
