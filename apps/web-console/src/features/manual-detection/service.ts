import type { ApiClient } from '@/api/client'
import type {
  AlgorithmOutcomeV2,
  BatchItemStatus,
  BatchSource,
  BatchStatus,
  DetectionBatch,
  DetectionBatchItem,
  JsonObject,
  QuickReviewDecision,
  QuickReviewRecord,
  UsageStage,
} from '@/api/generated'

const BATCH_STATUSES = new Set<BatchStatus>([
  'DRAFT', 'UPLOADING', 'READY', 'PROCESSING', 'COMPLETED',
  'PARTIALLY_COMPLETED', 'FAILED', 'CANCELLED',
])
const ITEM_STATUSES = new Set<BatchItemStatus>([
  'PENDING_UPLOAD', 'UPLOADING', 'READY', 'QUEUED', 'PROCESSING',
  'COMPLETED', 'QUALITY_REJECTED', 'FAILED', 'CANCELLED',
])
const OUTCOMES = new Set<AlgorithmOutcomeV2>([
  'QUALIFIED', 'UNQUALIFIED', 'INCONCLUSIVE',
])
const SOURCES = new Set<BatchSource>(['MANUAL_UPLOAD', 'PRODUCTION_CAPTURE'])
const STAGES = new Set<UsageStage>([
  'NEW_BLADE', 'AFTER_ONE_WHEEL', 'AFTER_TWO_WHEELS',
  'AFTER_THREE_WHEELS', 'OTHER', 'UNSPECIFIED',
])
const DECISIONS = new Set<QuickReviewDecision>([
  'DEFECT_CONFIRMED', 'NO_DEFECT_CONFIRMED', 'UNABLE_TO_DETERMINE',
])

export interface ManualDetectionCapabilities {
  readonly enabled: boolean
  readonly maximumItemsPerBatch: number
  readonly maximumObjectBytes: number
  readonly allowedMediaTypes: readonly ('image/png' | 'image/jpeg')[]
  readonly uploadTtlSeconds: number
}

export interface DetectionBatchDetail extends DetectionBatch {
  readonly items: readonly DetectionBatchItem[]
}

export interface DetectionBatchPage {
  readonly items: readonly DetectionBatch[]
  readonly nextCursor?: string
}

export interface UploadItemIntent {
  readonly item: DetectionBatchItem
  readonly method: 'PUT'
  readonly url: string
  readonly headers: Readonly<Record<string, string>>
  readonly expiresAt: string
}

export interface DetectionBatchItemAccess {
  readonly item: DetectionBatchItem
  readonly readUrl?: string
  readonly readExpiresAt?: string
  readonly resultReadUrl?: string
  readonly resultReadExpiresAt?: string
  readonly errorCode?: string
  readonly retryable?: boolean
  readonly attemptId?: string
}

export interface PreparedImage {
  readonly file: File
  readonly mediaType: 'image/png' | 'image/jpeg'
  readonly sha256: string
}

export class ManualDetectionService {
  constructor(
    private readonly api: ApiClient,
    private readonly uploadFetcher: typeof fetch = (input, init) => window.fetch(input, init),
    private readonly idFactory: () => string = () => crypto.randomUUID(),
  ) {}

  async capabilities(): Promise<ManualDetectionCapabilities> {
    return parseCapabilities(await this.api.getManualDetectionCapabilitiesV2())
  }

  async list(cursor?: string): Promise<DetectionBatchPage> {
    return parsePage(await this.api.listDetectionBatchesV2({
      query: cursor === undefined ? {} : { cursor },
    }))
  }

  async get(batchId: string): Promise<DetectionBatchDetail> {
    return parseBatchDetail(await this.api.getDetectionBatchV2({
      path: { batch_id: batchId },
    }))
  }

  async getItem(batchId: string, itemId: string): Promise<DetectionBatchItemAccess> {
    const value = await this.api.getDetectionBatchItemV2({
      path: { batch_id: batchId, item_id: itemId },
    })
    const item = parseItem(value)
    let readUrl: string | undefined
    let readExpiresAt: string | undefined
    if (value.read !== undefined) {
      if (!object(value.read) || typeof value.read.url !== 'string'
        || typeof value.read.expires_at !== 'string') throw incompatible()
      readUrl = value.read.url; readExpiresAt = value.read.expires_at
    }
    let resultReadUrl: string | undefined
    let resultReadExpiresAt: string | undefined
    let errorCode: string | undefined
    let retryable: boolean | undefined
    let attemptId: string | undefined
    if (value.execution !== undefined) {
      if (!object(value.execution) || typeof value.execution.attempt_id !== 'string') throw incompatible()
      attemptId = value.execution.attempt_id
      if (value.execution.error_code !== undefined) {
        if (typeof value.execution.error_code !== 'string' || typeof value.execution.retryable !== 'boolean') throw incompatible()
        errorCode = value.execution.error_code; retryable = value.execution.retryable
      }
      if (value.execution.result_read !== undefined) {
        if (!object(value.execution.result_read) || typeof value.execution.result_read.url !== 'string'
          || typeof value.execution.result_read.expires_at !== 'string') throw incompatible()
        resultReadUrl = value.execution.result_read.url
        resultReadExpiresAt = value.execution.result_read.expires_at
      }
    }
    return Object.freeze({ item, ...(readUrl === undefined ? {} : { readUrl, readExpiresAt }),
      ...(resultReadUrl === undefined ? {} : { resultReadUrl, resultReadExpiresAt }),
      ...(errorCode === undefined ? {} : { errorCode, retryable }),
      ...(attemptId === undefined ? {} : { attemptId }) })
  }

  async create(stage: UsageStage, note?: string, idempotencyKey = this.idFactory()): Promise<DetectionBatch> {
    return parseBatch(await this.api.createDetectionBatchV2({
      headers: { 'Idempotency-Key': idempotencyKey },
      body: {
        usage_stage: stage,
        ...(note === undefined || note.trim() === '' ? {} : { usage_stage_note: note.trim() }),
      },
    }))
  }

  async addItem(batchId: string, prepared: PreparedImage, idempotencyKey = this.idFactory()): Promise<UploadItemIntent> {
    const value = await this.api.addDetectionBatchItemV2({
      path: { batch_id: batchId },
      headers: { 'Idempotency-Key': idempotencyKey },
      body: {
        file_name: prepared.file.name,
        size_bytes: prepared.file.size,
        media_type: prepared.mediaType,
        sha256: prepared.sha256,
      },
    })
    return parseUploadIntent(value)
  }

  async renewUpload(batchId: string, itemId: string, idempotencyKey = this.idFactory()): Promise<UploadItemIntent> {
    const value = await this.api.renewDetectionBatchItemUploadV2({
      path: { batch_id: batchId, item_id: itemId },
      headers: { 'Idempotency-Key': idempotencyKey },
    })
    return parseUploadIntent(value)
  }

  async upload(intent: UploadItemIntent, file: File): Promise<void> {
    const response = await this.uploadFetcher(intent.url, {
      method: intent.method,
      headers: intent.headers,
      body: file,
      credentials: 'omit',
    })
    if (!response.ok) throw new Error('TD-MANUAL-UPLOAD-FAILED-001')
  }

  async complete(batchId: string, prepared: PreparedImage, intent: UploadItemIntent, idempotencyKey = this.idFactory()): Promise<DetectionBatchItem> {
    return parseItem(await this.api.completeDetectionBatchItemUploadV2({
      path: { batch_id: batchId, item_id: intent.item.batch_item_id },
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { sha256: prepared.sha256, size_bytes: prepared.file.size },
    }))
  }

  async submit(batchId: string, expectedVersion: number, idempotencyKey = this.idFactory()): Promise<DetectionBatch> {
    return parseBatch(await this.api.submitDetectionBatchV2({
      path: { batch_id: batchId },
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { expected_version: expectedVersion },
    }))
  }

  async quickReview(batchId: string, itemId: string, decision: QuickReviewDecision,
    supersedesRecordId?: string, idempotencyKey = this.idFactory()): Promise<QuickReviewRecord> {
    return parseQuickReview(await this.api.putQuickReviewV2({
      path: { batch_id: batchId, item_id: itemId },
      headers: { 'Idempotency-Key': idempotencyKey },
      body: {
        decision,
        ...(supersedesRecordId === undefined ? {} : { supersedes_record_id: supersedesRecordId }),
      },
    }))
  }
}

export async function prepareImage(file: File): Promise<PreparedImage> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  const mediaType = detectImageType(bytes)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  const sha256 = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('')
  return Object.freeze({ file, mediaType, sha256 })
}

export function detectImageType(bytes: Uint8Array): 'image/png' | 'image/jpeg' {
  if (bytes.length >= 8 && [137, 80, 78, 71, 13, 10, 26, 10]
    .every((value, index) => bytes[index] === value)) return 'image/png'
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'image/jpeg'
  throw new Error('TD-MANUAL-FILE-TYPE-001')
}

export function resultPriority(item: DetectionBatchItem): number {
  if (item.status === 'QUALITY_REJECTED' || item.status === 'FAILED') return 0
  if (item.algorithm_outcome === 'INCONCLUSIVE') return 1
  if (item.algorithm_outcome === 'UNQUALIFIED') return 2
  if (item.algorithm_outcome === 'QUALIFIED') return 3
  return 4
}

function parseCapabilities(value: JsonObject): ManualDetectionCapabilities {
  if (typeof value.enabled !== 'boolean' || !positive(value.maximum_items_per_batch)
    || !positive(value.maximum_object_bytes) || !positive(value.upload_ttl_seconds)
    || !Array.isArray(value.allowed_media_types)
    || !value.allowed_media_types.every((item) => item === 'image/png' || item === 'image/jpeg')) throw incompatible()
  return Object.freeze({
    enabled: value.enabled,
    maximumItemsPerBatch: value.maximum_items_per_batch,
    maximumObjectBytes: value.maximum_object_bytes,
    allowedMediaTypes: Object.freeze(value.allowed_media_types),
    uploadTtlSeconds: value.upload_ttl_seconds,
  })
}

function parsePage(value: JsonObject): DetectionBatchPage {
  if (!Array.isArray(value.items) || !(value.next_cursor === undefined || typeof value.next_cursor === 'string')) throw incompatible()
  return Object.freeze({ items: Object.freeze(value.items.map(parseBatch)), ...(value.next_cursor === undefined ? {} : { nextCursor: value.next_cursor }) })
}

function parseBatchDetail(value: JsonObject): DetectionBatchDetail {
  if (!Array.isArray(value.items)) throw incompatible()
  return Object.freeze({ ...parseBatch(value), items: Object.freeze(value.items.map(parseItem)) })
}

function parseBatch(value: unknown): DetectionBatch {
  if (!object(value) || typeof value.batch_id !== 'string' || typeof value.batch_no !== 'string'
    || !SOURCES.has(value.source as BatchSource) || typeof value.created_by !== 'string'
    || !STAGES.has(value.usage_stage as UsageStage) || !BATCH_STATUSES.has(value.status as BatchStatus)
    || !object(value.counts) || typeof value.created_at !== 'string' || typeof value.updated_at !== 'string'
    || !positive(value.version)) throw incompatible()
  const counts = value.counts
  for (const key of ['total', 'completed', 'defect_suspected', 'normal', 'inconclusive', 'quality_rejected', 'technical_failed']) {
    if (!nonNegative(counts[key])) throw incompatible()
  }
  return Object.freeze(value) as DetectionBatch
}

function parseItem(value: unknown): DetectionBatchItem {
  if (!object(value) || typeof value.batch_item_id !== 'string' || typeof value.batch_id !== 'string'
    || !object(value.image) || !ITEM_STATUSES.has(value.status as BatchItemStatus)
    || !(value.algorithm_outcome === undefined || OUTCOMES.has(value.algorithm_outcome as AlgorithmOutcomeV2))
    || !(value.quick_review_decision === undefined || DECISIONS.has(value.quick_review_decision as QuickReviewDecision))
    || typeof value.created_at !== 'string' || typeof value.updated_at !== 'string') throw incompatible()
  return Object.freeze(value) as DetectionBatchItem
}

function parseUploadIntent(value: JsonObject): UploadItemIntent {
  if (!object(value.upload) || value.upload.method !== 'PUT' || typeof value.upload.url !== 'string'
    || !object(value.upload.headers) || typeof value.upload.expires_at !== 'string') throw incompatible()
  const headers: Record<string, string> = {}
  for (const [key, item] of Object.entries(value.upload.headers)) {
    if (typeof item !== 'string') throw incompatible()
    headers[key] = item
  }
  return Object.freeze({ item: parseItem(value), method: 'PUT', url: value.upload.url,
    headers: Object.freeze(headers), expiresAt: value.upload.expires_at })
}

function parseQuickReview(value: JsonObject): QuickReviewRecord {
  if (typeof value.review_record_id !== 'string' || typeof value.batch_item_id !== 'string'
    || !DECISIONS.has(value.decision as QuickReviewDecision) || typeof value.submitted_by !== 'string'
    || typeof value.submitted_at !== 'string' || typeof value.idempotency_key !== 'string'
    || !(value.supersedes_record_id === undefined || typeof value.supersedes_record_id === 'string')) throw incompatible()
  return Object.freeze(value) as QuickReviewRecord
}

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function nonNegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function incompatible(): Error { return new Error('TD-CONTRACT-V2-INCOMPATIBLE-001') }
