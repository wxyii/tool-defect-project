import type {
  AlgorithmOutcome,
  BusinessDisposition,
  CaptureStatus,
  DetectionDetail,
  DetectionPage,
  DetectionSummary,
  ExecutionStatus,
  ImageAccessTicketResponse,
  ImageKind,
  ImageReference,
  JsonObject,
  ReviewStatus,
} from '@/api/generated'
import type { ApiClient } from '@/api/client'

const TASK_STATES = new Set<ExecutionStatus>([
  'QUEUED',
  'RUNNING',
  'SUCCEEDED',
  'RETRY_WAIT',
  'DEAD',
])
const CAPTURE_STATES = new Set<CaptureStatus>([
  'CREATED',
  'UPLOADING',
  'READY',
  'SUBMITTED',
  'PROCESSING',
  'REVIEW_PENDING',
  'FINALIZED',
  'FAILED',
])
const OUTCOMES = new Set<AlgorithmOutcome>([
  'QUALIFIED',
  'UNQUALIFIED',
  'INCONCLUSIVE',
])
const DISPOSITIONS = new Set<BusinessDisposition>(['PASS', 'FAIL', 'HOLD'])
const REVIEWS = new Set<ReviewStatus>([
  'PENDING',
  'CLAIMED',
  'SECOND_REVIEW_PENDING',
  'ESCALATED',
  'RESOLVED',
  'CANCELLED',
])
const IMAGE_KINDS = new Set<ImageKind>([
  'RAW',
  'THUMBNAIL',
  'DEFECT_MASK',
  'HEATMAP',
  'OVERLAY',
  'POLAR',
  'REVIEW_MASK',
])

export interface DetectionFilters {
  readonly cursor?: string
  readonly pageSize?: number
  readonly businessDisposition?: BusinessDisposition
  readonly algorithmOutcome?: AlgorithmOutcome
  readonly modelVersion?: string
}

export class DetectionService {
  constructor(private readonly api: ApiClient) {}

  async list(filters: DetectionFilters = {}): Promise<DetectionPage> {
    const query: Record<string, string | number> = {
      page_size: filters.pageSize ?? 25,
    }
    if (filters.cursor !== undefined) query.cursor = filters.cursor
    if (filters.businessDisposition !== undefined) {
      query.business_disposition = filters.businessDisposition
    }
    if (filters.algorithmOutcome !== undefined) {
      query.algorithm_outcome = filters.algorithmOutcome
    }
    if (filters.modelVersion !== undefined && filters.modelVersion.trim() !== '') {
      query.model_version = filters.modelVersion.trim()
    }
    return detectionPage(
      await this.api.listDetections({ query } as JsonObject),
    )
  }

  async get(detectionTaskId: string): Promise<DetectionDetail> {
    return parseDetectionDetail(
      await this.api.getDetection({
        path: { detection_task_id: detectionTaskId },
      }),
    )
  }

  async imageTicket(imageId: string): Promise<ImageAccessTicketResponse> {
    return imageTicket(
      await this.api.createImageAccessTicket({
        path: { image_id: imageId },
        body: { purpose: 'VIEW' },
      }),
    )
  }
}

function detectionPage(value: JsonObject): DetectionPage {
  exact(value, ['items', 'next_cursor', 'has_more'])
  if (
    !Array.isArray(value.items)
    || typeof value.has_more !== 'boolean'
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')
  ) {
    throw incompatible()
  }
  return Object.freeze({
    items: Object.freeze(value.items.map((item) => detectionSummary(item))),
    next_cursor: value.next_cursor,
    has_more: value.has_more,
  })
}

export function parseDetectionDetail(value: JsonObject): DetectionDetail {
  exact(value, [
    'capture',
    'detection',
    'attempts',
    'disposition_history',
    'images',
    'versions',
  ])
  if (
    !isObject(value.capture)
    || !isObject(value.detection)
    || !Array.isArray(value.attempts)
    || !value.attempts.every(isObject)
    || !Array.isArray(value.disposition_history)
    || !value.disposition_history.every(isObject)
    || !Array.isArray(value.images)
    || !isObject(value.versions)
  ) {
    throw incompatible()
  }
  const capture = value.capture
  exactOptional(capture, [
    'capture_id',
    'capture_status',
    'business_disposition',
    'poll_after_ms',
    'detection',
    'review',
  ])
  if (
    !isUuid(capture.capture_id)
    || !CAPTURE_STATES.has(capture.capture_status as CaptureStatus)
    || !(
      capture.business_disposition === null
      || DISPOSITIONS.has(capture.business_disposition as BusinessDisposition)
    )
    || !isFiniteNumber(capture.poll_after_ms)
  ) {
    throw incompatible()
  }
  if (
    capture.review !== undefined
    && (
      !isObject(capture.review)
      || !REVIEWS.has(capture.review.status as ReviewStatus)
    )
  ) {
    throw incompatible()
  }
  const summary = detectionSummary(value.detection)
  const images = value.images.map(imageReference)
  return Object.freeze({
    capture: Object.freeze({
      capture_id: capture.capture_id,
      capture_status: capture.capture_status as CaptureStatus,
      business_disposition:
        capture.business_disposition as BusinessDisposition | null,
      poll_after_ms: capture.poll_after_ms,
      ...(capture.detection === undefined ? {} : { detection: summary }),
      ...(capture.review === undefined
        ? {}
        : {
            review: Object.freeze({
              status: capture.review.status as ReviewStatus,
            }),
          }),
    }),
    detection: summary,
    attempts: Object.freeze(value.attempts),
    disposition_history: Object.freeze(value.disposition_history),
    images: Object.freeze(images),
    versions: Object.freeze(value.versions),
  }) as DetectionDetail
}

function detectionSummary(value: unknown): DetectionSummary {
  if (!isObject(value)) throw incompatible()
  exactOptional(value, [
    'detection_task_id',
    'task_status',
    'algorithm_outcome',
    'confidence',
    'model_version',
  ])
  if (
    !isUuid(value.detection_task_id)
    || !TASK_STATES.has(value.task_status as ExecutionStatus)
    || !(
      value.algorithm_outcome === undefined
      || value.algorithm_outcome === null
      || OUTCOMES.has(value.algorithm_outcome as AlgorithmOutcome)
    )
    || !(
      value.confidence === undefined
      || value.confidence === null
      || (
        isFiniteNumber(value.confidence)
        && value.confidence >= 0
        && value.confidence <= 1
      )
    )
    || !(
      value.model_version === undefined
      || value.model_version === null
      || typeof value.model_version === 'string'
    )
  ) {
    throw incompatible()
  }
  return Object.freeze({
    detection_task_id: value.detection_task_id,
    task_status: value.task_status as ExecutionStatus,
    ...(value.algorithm_outcome === undefined
      ? {}
      : { algorithm_outcome: value.algorithm_outcome as AlgorithmOutcome | null }),
    ...(value.confidence === undefined
      ? {}
      : { confidence: value.confidence }),
    ...(value.model_version === undefined
      ? {}
      : { model_version: value.model_version as string | null }),
  })
}

function imageReference(value: unknown): ImageReference {
  if (!isObject(value) || !isObject(value.object)) throw incompatible()
  exactOptional(value, [
    'image_id',
    'kind',
    'object',
    'width',
    'height',
    'image_role',
  ])
  exactOptional(value.object, [
    'bucket',
    'object_key',
    'object_version',
    'sha256',
    'size_bytes',
    'media_type',
  ])
  if (
    !isUuid(value.image_id)
    || !IMAGE_KINDS.has(value.kind as ImageKind)
    || !isFiniteNumber(value.width)
    || !isFiniteNumber(value.height)
    || typeof value.object.bucket !== 'string'
    || typeof value.object.object_key !== 'string'
    || typeof value.object.sha256 !== 'string'
    || !isFiniteNumber(value.object.size_bytes)
    || ![
      'image/png',
      'image/jpeg',
      'application/json',
      'application/octet-stream',
    ].includes(String(value.object.media_type))
  ) {
    throw incompatible()
  }
  return Object.freeze(value) as ImageReference
}

function imageTicket(value: JsonObject): ImageAccessTicketResponse {
  exact(value, ['method', 'url', 'expires_at'])
  if (
    value.method !== 'GET'
    || typeof value.url !== 'string'
    || typeof value.expires_at !== 'string'
    || !value.expires_at.endsWith('Z')
  ) {
    throw incompatible()
  }
  return Object.freeze(value) as ImageAccessTicketResponse
}

function exact(value: JsonObject, keys: readonly string[]): void {
  if (
    Object.keys(value).length !== keys.length
    || Object.keys(value).some((key) => !keys.includes(key))
  ) {
    throw incompatible()
  }
}

function exactOptional(value: JsonObject, keys: readonly string[]): void {
  if (Object.keys(value).some((key) => !keys.includes(key))) {
    throw incompatible()
  }
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isUuid(value: unknown): value is `${string}-${string}-${string}-${string}-${string}` {
  return (
    typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value,
    )
  )
}

function incompatible(): Error {
  return new Error('TD-CONTRACT-INCOMPATIBLE-001')
}
