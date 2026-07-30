import type { ApiClient } from '@/api/client'
import type {
  JsonObject,
  ObjectCompleteResponse,
  ReviewSubmissionRequest,
  ReviewSubmissionResponse,
  ReviewTask,
  ReviewTaskPage,
  ReviewWorkspace,
  UploadTicketResponse,
} from '@/api/generated'
import { parseDetectionDetail } from '@/features/detections/service'

const REVIEW_STATES = new Set([
  'PENDING',
  'CLAIMED',
  'SECOND_REVIEW_PENDING',
  'ESCALATED',
  'RESOLVED',
  'CANCELLED',
])
const PRIORITIES = new Set(['P0', 'P1', 'P2', 'P3'])
const DISPOSITIONS = new Set(['PASS', 'FAIL', 'HOLD'])
const UPLOAD_RECEIPT = 'x-tool-defect-upload-receipt'

export interface ReviewFilters {
  readonly cursor?: string
  readonly pageSize?: number
  readonly status?: ReviewTask['status']
}

export class ReviewService {
  constructor(
    private readonly api: ApiClient,
    private readonly fetcher: typeof fetch = fetch,
  ) {}

  async list(filters: ReviewFilters = {}): Promise<ReviewTaskPage> {
    const query: Record<string, string | number> = {
      page_size: filters.pageSize ?? 25,
    }
    if (filters.cursor !== undefined) query.cursor = filters.cursor
    if (filters.status !== undefined) query.status = filters.status
    return reviewTaskPage(await this.api.listReviewTasks({ query }))
  }

  async workspace(reviewTaskId: string): Promise<ReviewWorkspace> {
    const value = await this.api.getReviewWorkspace({
      path: { review_task_id: reviewTaskId },
    })
    exact(value, ['task', 'evidence'])
    if (!isObject(value.task) || !isObject(value.evidence)) {
      throw incompatible()
    }
    return Object.freeze({
      task: reviewTask(value.task),
      evidence: parseDetectionDetail(value.evidence),
    })
  }

  claim(task: ReviewTask, reason = '开始人工复核'): Promise<ReviewTask> {
    return this.action('claim', task, reason)
  }

  release(task: ReviewTask, reason: string): Promise<ReviewTask> {
    return this.action('release', task, reason)
  }

  async submit(
    task: ReviewTask,
    submission: ReviewSubmissionRequest,
  ): Promise<ReviewSubmissionResponse> {
    return reviewSubmissionResponse(
      await this.api.submitReview({
        path: { review_task_id: task.review_task_id },
        headers: commandHeaders(task.record_version),
        body: submission as unknown as JsonObject,
      }),
    )
  }

  async createMaskTicket(
    task: ReviewTask,
    blob: Blob,
    width: number,
    height: number,
  ): Promise<{ readonly ticket: UploadTicketResponse; readonly sha256: string }> {
    const sha256 = await blobSha256(blob)
    const value = await this.api.createAnnotationUploadTicket({
      path: { review_task_id: task.review_task_id },
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: {
        media_type: 'image/png',
        size_bytes: blob.size,
        sha256,
        width,
        height,
      },
    })
    return Object.freeze({ ticket: uploadTicket(value), sha256 })
  }

  async uploadMask(ticket: UploadTicketResponse, blob: Blob): Promise<string> {
    const headers = new Headers()
    let receipt: string | null = null
    for (const [name, rawValue] of Object.entries(ticket.upload.headers)) {
      if (typeof rawValue !== 'string') throw incompatible()
      if (name.toLowerCase() === UPLOAD_RECEIPT) {
        receipt = rawValue
      } else {
        headers.set(name, rawValue)
      }
    }
    if (receipt === null || receipt.length === 0) {
      throw new Error('TD-UPLOAD-RECEIPT-001')
    }
    requireSafeTicketUrl(ticket.upload.url)
    const response = await this.fetcher(ticket.upload.url, {
      method: 'PUT',
      headers,
      body: blob,
    })
    if (!response.ok) throw new Error('TD-UPLOAD-MASK-001')
    return receipt
  }

  async completeMask(
    task: ReviewTask,
    ticket: UploadTicketResponse,
    blob: Blob,
    sha256: string,
    uploadReceipt: string,
  ): Promise<ObjectCompleteResponse> {
    return objectCompleteResponse(
      await this.api.completeReviewAnnotation({
        path: {
          review_task_id: task.review_task_id,
          image_id: ticket.image_id,
        },
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: {
          size_bytes: blob.size,
          sha256,
          upload_receipt: uploadReceipt,
        },
      }),
    )
  }

  private async action(
    kind: 'claim' | 'release',
    task: ReviewTask,
    reason: string,
  ): Promise<ReviewTask> {
    const request = {
      path: { review_task_id: task.review_task_id },
      headers: commandHeaders(task.record_version),
      body: {
        client_request_id: crypto.randomUUID(),
        reason,
      },
    }
    const value = kind === 'claim'
      ? await this.api.claimReviewTask(request)
      : await this.api.releaseReviewTask(request)
    return reviewTask(value)
  }
}

export async function blobSha256(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
  return Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
}

function commandHeaders(recordVersion: number): JsonObject {
  return {
    'Idempotency-Key': crypto.randomUUID(),
    'If-Match': `"${recordVersion}"`,
  }
}

function reviewTaskPage(value: JsonObject): ReviewTaskPage {
  exact(value, ['items', 'next_cursor', 'has_more'])
  if (
    !Array.isArray(value.items)
    || !value.items.every(isObject)
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')
    || typeof value.has_more !== 'boolean'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    items: Object.freeze(value.items.map(reviewTask)),
    next_cursor: value.next_cursor,
    has_more: value.has_more,
  })
}

function reviewTask(value: JsonObject): ReviewTask {
  exact(value, [
    'review_task_id',
    'capture_id',
    'status',
    'priority',
    'lease_expires_at',
    'record_version',
  ])
  if (
    !isUuid(value.review_task_id)
    || !isUuid(value.capture_id)
    || !REVIEW_STATES.has(String(value.status))
    || !PRIORITIES.has(String(value.priority))
    || !(
      value.lease_expires_at === null
      || value.lease_expires_at === undefined
      || isUtcTimestamp(value.lease_expires_at)
    )
    || !Number.isInteger(value.record_version)
    || Number(value.record_version) < 0
  ) {
    throw incompatible()
  }
  return Object.freeze({
    review_task_id: value.review_task_id,
    capture_id: value.capture_id,
    status: value.status,
    priority: value.priority,
    ...(value.lease_expires_at === undefined
      ? {}
      : { lease_expires_at: value.lease_expires_at }),
    record_version: value.record_version,
  }) as ReviewTask
}

function reviewSubmissionResponse(value: JsonObject): ReviewSubmissionResponse {
  exact(value, [
    'review_record_id',
    'task_status',
    'business_disposition',
    'record_version',
  ])
  if (
    !isUuid(value.review_record_id)
    || !REVIEW_STATES.has(String(value.task_status))
    || !DISPOSITIONS.has(String(value.business_disposition))
    || !Number.isInteger(value.record_version)
  ) {
    throw incompatible()
  }
  return Object.freeze(value) as ReviewSubmissionResponse
}

function uploadTicket(value: JsonObject): UploadTicketResponse {
  exact(value, ['image_id', 'upload'])
  if (!isUuid(value.image_id) || !isObject(value.upload)) {
    throw incompatible()
  }
  exact(value.upload, ['method', 'url', 'headers', 'expires_at'])
  if (
    value.upload.method !== 'PUT'
    || typeof value.upload.url !== 'string'
    || !isObject(value.upload.headers)
    || !isUtcTimestamp(value.upload.expires_at)
  ) {
    throw incompatible()
  }
  return Object.freeze({
    image_id: value.image_id,
    upload: Object.freeze({
      method: 'PUT',
      url: value.upload.url,
      headers: Object.freeze({ ...value.upload.headers }),
      expires_at: value.upload.expires_at,
    }),
  }) as UploadTicketResponse
}

function objectCompleteResponse(value: JsonObject): ObjectCompleteResponse {
  exact(value, ['image_id', 'state', 'sha256'])
  if (
    !isUuid(value.image_id)
    || value.state !== 'AVAILABLE'
    || typeof value.sha256 !== 'string'
    || !/^[0-9a-f]{64}$/.test(value.sha256)
  ) {
    throw incompatible()
  }
  return Object.freeze(value) as ObjectCompleteResponse
}

function requireSafeTicketUrl(value: string): void {
  const url = new URL(value)
  const local = url.hostname === 'localhost' || url.hostname === '127.0.0.1'
  if (
    !(url.protocol === 'https:' || (url.protocol === 'http:' && local))
    || url.username !== ''
    || url.password !== ''
  ) {
    throw new Error('TD-STORAGE-TICKET-INSECURE')
  }
}

function exact(value: JsonObject, fields: readonly string[]): void {
  const allowed = new Set(fields)
  if (Object.keys(value).some((field) => !allowed.has(field))) {
    throw incompatible()
  }
}

function isObject(value: unknown): value is JsonObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isUuid(value: unknown): value is ReviewTask['review_task_id'] {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
      .test(value)
}

function isUtcTimestamp(value: unknown): value is `${string}Z` {
  return typeof value === 'string'
    && value.endsWith('Z')
    && Number.isFinite(Date.parse(value))
}

function incompatible(): Error {
  return new Error('TD-CONTRACT-INCOMPATIBLE-001')
}
