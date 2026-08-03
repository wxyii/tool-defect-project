import type { ApiClient } from '@/api/client'
import type { JsonObject } from '@/api/generated'

export const SAMPLE_LABELS = [
  'CORRECT_DETECTION',
  'FALSE_POSITIVE',
  'FALSE_NEGATIVE',
  'LOCALIZATION_INACCURATE',
  'IMAGE_UNUSABLE',
  'UNCONFIRMED',
] as const
export type SampleLabel = typeof SAMPLE_LABELS[number]

export const CANDIDATE_STATUSES = ['PENDING', 'INCLUDED', 'EXCLUDED', 'EXPORTED'] as const
export type CandidateStatus = typeof CANDIDATE_STATUSES[number]
export type CandidateDecision = 'INCLUDE' | 'EXCLUDE'

export interface SampleObjectReference {
  readonly bucket: string
  readonly objectKey: string
  readonly mediaType: string
  readonly sha256?: string
  readonly sizeBytes?: number
  readonly objectVersion?: string
}

export interface AdminFeedback {
  readonly feedbackId: string
  readonly batchItemId: string
  readonly label: SampleLabel
  readonly note?: string
  readonly sourceReviewRecordId?: string
  readonly supersedesFeedbackId?: string
  readonly revision: number
  readonly submittedBy?: string
  readonly submittedAt: string
}

export interface AdminDetectionItem {
  readonly batchItemId: string
  readonly batchId: string
  readonly status: string
  readonly algorithmOutcome?: string
  readonly employeeFeedback?: string
  readonly usageStage?: string
  readonly image: SampleObjectReference
  readonly createdAt: string
  readonly updatedAt: string
  readonly latestAdminFeedback?: AdminFeedback
}

export interface SampleCandidate {
  readonly candidateId: string
  readonly batchItemId: string
  readonly feedbackId: string
  readonly status: CandidateStatus
  readonly decisionNote?: string
  readonly sourceSnapshot: JsonObject
  readonly latestDecisionId?: string
  readonly exportJobId?: string
  readonly createdAt: string
}

export interface SampleExternalReceipt {
  readonly receiptId: string
  readonly sampleExportJobId: string
  readonly receiverName: string
  readonly externalReference?: string
  readonly receiptNote?: string
  readonly recordedBy: string
  readonly recordedAt: string
}

export interface SampleExportJob {
  readonly jobId: string
  readonly filterSnapshot: Readonly<Record<string, string>>
  readonly candidateCount: number
  readonly exportedCount: number
  readonly failedCount: number
  readonly status: string
  readonly packageReference?: SampleObjectReference
  readonly manifestReference?: SampleObjectReference
  readonly failedCandidateIds: readonly string[]
  readonly externalReceipts: readonly SampleExternalReceipt[]
  readonly createdAt: string
  readonly expiresAt?: string
}

export interface SampleDownloadTicket {
  readonly ticketId: string
  readonly downloadUrl: string
  readonly expiresAt: string
}

export interface AdminDetectionFilter {
  readonly label?: SampleLabel
  readonly status?: string
  readonly usageStage?: string
  readonly cursor?: string
}

export interface AdminDetectionPage {
  readonly items: readonly AdminDetectionItem[]
  readonly nextCursor?: string
}

export interface SampleCandidatePage {
  readonly items: readonly SampleCandidate[]
  readonly nextCursor?: string
}

export class SampleLibraryService {
  constructor(
    private readonly api: ApiClient,
    private readonly idFactory: () => string = () => crypto.randomUUID(),
  ) {}

  async listAdmin(filter: AdminDetectionFilter = {}): Promise<AdminDetectionPage> {
    const query: Record<string, unknown> = {}
    if (filter.cursor !== undefined) query.cursor = filter.cursor
    if (filter.label !== undefined) query.label = filter.label
    if (filter.status !== undefined && filter.status !== '') query.status = filter.status
    if (filter.usageStage !== undefined && filter.usageStage !== '') query.usage_stage = filter.usageStage
    return parseAdminPage(await this.api.listAdminDetectionItemsV2({ query }))
  }

  async saveFeedback(
    itemId: string,
    label: SampleLabel,
    note?: string,
    supersedesFeedbackId?: string,
    idempotencyKey = this.idFactory(),
  ): Promise<AdminFeedback> {
    const body: Record<string, unknown> = { label }
    if (note !== undefined && note.trim() !== '') body.note = note.trim()
    if (supersedesFeedbackId !== undefined) body.supersedes_feedback_id = supersedesFeedbackId
    return parseFeedback(await this.api.createAdminFeedbackV2({
      path: { item_id: itemId },
      headers: { 'Idempotency-Key': idempotencyKey },
      body,
    }))
  }

  async listCandidates(status?: CandidateStatus, cursor?: string): Promise<SampleCandidatePage> {
    const query: Record<string, unknown> = {}
    if (status !== undefined) query.status = status
    if (cursor !== undefined) query.cursor = cursor
    return parseCandidatePage(await this.api.listSampleCandidatesV2({ query }))
  }

  async createCandidate(
    itemId: string,
    feedbackId: string,
    idempotencyKey = this.idFactory(),
  ): Promise<SampleCandidate> {
    return parseCandidate(await this.api.createSampleCandidateV2({
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { batch_item_id: itemId, feedback_id: feedbackId },
    }))
  }

  async decideCandidate(
    candidateId: string,
    decision: CandidateDecision,
    note?: string,
    supersedesDecisionId?: string,
    idempotencyKey = this.idFactory(),
  ): Promise<SampleCandidate> {
    const body: Record<string, unknown> = { decision }
    if (note !== undefined && note.trim() !== '') body.note = note.trim()
    if (supersedesDecisionId !== undefined) body.supersedes_decision_id = supersedesDecisionId
    return parseCandidate(await this.api.decideSampleCandidateV2({
      path: { candidate_id: candidateId },
      headers: { 'Idempotency-Key': idempotencyKey },
      body,
    }))
  }

  async createExport(
    candidateIds: readonly string[],
    filterSnapshot: Readonly<Record<string, string>> = Object.freeze({}),
    idempotencyKey = this.idFactory(),
  ): Promise<SampleExportJob> {
    const body: Record<string, unknown> = { candidate_ids: [...candidateIds] }
    if (Object.keys(filterSnapshot).length > 0) body.filter_snapshot = { ...filterSnapshot }
    return parseExport(await this.api.createSampleExportV2({
      headers: { 'Idempotency-Key': idempotencyKey },
      body,
    }))
  }

  async getExport(jobId: string): Promise<SampleExportJob> {
    return parseExport(await this.api.getSampleExportV2({ path: { export_job_id: jobId } }))
  }

  async issueDownloadTicket(
    jobId: string,
    idempotencyKey = this.idFactory(),
  ): Promise<SampleDownloadTicket> {
    return parseDownloadTicket(await this.api.createSampleExportDownloadTicketV2({
      path: { export_job_id: jobId },
      headers: { 'Idempotency-Key': idempotencyKey },
      body: {},
    }))
  }

  async recordExternalReceipt(
    jobId: string,
    receiverName: string,
    externalReference?: string,
    receiptNote?: string,
    idempotencyKey = this.idFactory(),
  ): Promise<SampleExternalReceipt> {
    const body: Record<string, unknown> = { receiver_name: receiverName.trim() }
    if (externalReference !== undefined && externalReference.trim() !== '') {
      body.external_reference = externalReference.trim()
    }
    if (receiptNote !== undefined && receiptNote.trim() !== '') {
      body.receipt_note = receiptNote.trim()
    }
    return parseExternalReceipt(await this.api.createSampleExternalReceiptV2({
      path: { export_job_id: jobId },
      headers: { 'Idempotency-Key': idempotencyKey },
      body,
    }))
  }
}

function parseAdminPage(value: JsonObject): AdminDetectionPage {
  allowed(value, ['items', 'next_cursor'])
  if (!Array.isArray(value.items)) throw incompatible()
  if (!(value.next_cursor === undefined || typeof value.next_cursor === 'string')) throw incompatible()
  return Object.freeze({
    items: Object.freeze(value.items.map(parseAdminItem)),
    ...(value.next_cursor === undefined ? {} : { nextCursor: value.next_cursor }),
  })
}

function parseAdminItem(value: unknown): AdminDetectionItem {
  if (!object(value)) throw incompatible()
  const item = value
  allowed(item, [
    'batch_item_id', 'batch_id', 'status', 'algorithm_outcome', 'employee_feedback',
    'usage_stage', 'image', 'created_at', 'updated_at', 'latest_admin_feedback',
  ])
  const image = item.image
  if (typeof item.batch_item_id !== 'string' || typeof item.batch_id !== 'string'
    || typeof item.status !== 'string' || !object(image)
    || typeof item.created_at !== 'string' || typeof item.updated_at !== 'string') throw incompatible()
  return Object.freeze({
    batchItemId: item.batch_item_id,
    batchId: item.batch_id,
    status: item.status,
    algorithmOutcome: nullableString(item.algorithm_outcome),
    employeeFeedback: nullableString(item.employee_feedback),
    usageStage: nullableString(item.usage_stage),
    image: parseObjectReference(image),
    createdAt: item.created_at,
    updatedAt: item.updated_at,
    ...(item.latest_admin_feedback == null
      ? {}
      : { latestAdminFeedback: parseFeedback(item.latest_admin_feedback) }),
  })
}

function parseFeedback(value: unknown): AdminFeedback {
  if (!object(value)) throw incompatible()
  const item = value
  allowed(item, [
    'feedback_id', 'batch_item_id', 'label', 'note', 'source_review_record_id',
    'supersedes_feedback_id', 'revision', 'submitted_by', 'submitted_at',
  ])
  if (typeof item.feedback_id !== 'string' || typeof item.batch_item_id !== 'string'
    || !SAMPLE_LABELS.includes(item.label as SampleLabel)
    || !integer(item.revision) || typeof item.submitted_at !== 'string') throw incompatible()
  return Object.freeze({
    feedbackId: item.feedback_id,
    batchItemId: item.batch_item_id,
    label: item.label as SampleLabel,
    ...optionalStringProperty('note', item.note),
    ...optionalStringProperty('sourceReviewRecordId', item.source_review_record_id),
    ...optionalStringProperty('supersedesFeedbackId', item.supersedes_feedback_id),
    revision: item.revision,
    ...optionalStringProperty('submittedBy', item.submitted_by),
    submittedAt: item.submitted_at,
  })
}

function parseCandidatePage(value: JsonObject): SampleCandidatePage {
  allowed(value, ['items', 'next_cursor'])
  if (!Array.isArray(value.items)) throw incompatible()
  if (!(value.next_cursor === undefined || typeof value.next_cursor === 'string')) throw incompatible()
  return Object.freeze({
    items: Object.freeze(value.items.map(parseCandidate)),
    ...(value.next_cursor === undefined ? {} : { nextCursor: value.next_cursor }),
  })
}

function parseCandidate(value: unknown): SampleCandidate {
  if (!object(value)) throw incompatible()
  const item = value
  allowed(item, [
    'sample_candidate_id', 'batch_item_id', 'feedback_id', 'status', 'decision_note',
    'source_snapshot', 'latest_decision_id', 'export_job_id', 'created_at',
  ])
  const snapshot = item.source_snapshot
  if (typeof item.sample_candidate_id !== 'string' || typeof item.batch_item_id !== 'string'
    || typeof item.feedback_id !== 'string' || !CANDIDATE_STATUSES.includes(item.status as CandidateStatus)
    || !object(snapshot) || typeof item.created_at !== 'string') throw incompatible()
  return Object.freeze({
    candidateId: item.sample_candidate_id,
    batchItemId: item.batch_item_id,
    feedbackId: item.feedback_id,
    status: item.status as CandidateStatus,
    ...optionalStringProperty('decisionNote', item.decision_note),
    sourceSnapshot: snapshot,
    ...optionalStringProperty('latestDecisionId', item.latest_decision_id),
    ...optionalStringProperty('exportJobId', item.export_job_id),
    createdAt: item.created_at,
  })
}

function parseExport(value: JsonObject): SampleExportJob {
  const item = value
  allowed(item, [
    'sample_export_job_id', 'filter_snapshot', 'candidate_count', 'exported_count',
    'failed_count', 'status', 'package', 'manifest', 'failed_candidate_ids',
    'external_receipts', 'created_at', 'expires_at',
  ])
  const rawFilter = item.filter_snapshot
  const rawFailed = item.failed_candidate_ids
  const rawReceipts = item.external_receipts
  if (typeof item.sample_export_job_id !== 'string' || !object(rawFilter)
    || !integer(item.candidate_count) || !integer(item.exported_count) || !integer(item.failed_count)
    || typeof item.status !== 'string' || !Array.isArray(rawFailed)
    || !rawFailed.every((value) => typeof value === 'string')
    || !(rawReceipts === undefined || Array.isArray(rawReceipts))
    || typeof item.created_at !== 'string') throw incompatible()
  const failedCandidateIds = rawFailed.filter((value): value is string => typeof value === 'string')
  const filterSnapshot: Record<string, string> = {}
  for (const [key, raw] of Object.entries(rawFilter)) {
    if (typeof raw !== 'string') throw incompatible()
    filterSnapshot[key] = raw
  }
  return Object.freeze({
    jobId: item.sample_export_job_id,
    filterSnapshot: Object.freeze(filterSnapshot),
    candidateCount: item.candidate_count,
    exportedCount: item.exported_count,
    failedCount: item.failed_count,
    status: item.status,
    ...(item.package == null ? {} : { packageReference: parseObjectReference(requireObject(item.package)) }),
    ...(item.manifest == null ? {} : { manifestReference: parseObjectReference(requireObject(item.manifest)) }),
    failedCandidateIds: Object.freeze(failedCandidateIds),
    externalReceipts: Object.freeze((rawReceipts ?? []).map(parseExternalReceipt)),
    createdAt: item.created_at,
    ...optionalStringProperty('expiresAt', item.expires_at),
  })
}

function parseExternalReceipt(value: unknown): SampleExternalReceipt {
  if (!object(value)) throw incompatible()
  const item = value
  allowed(item, [
    'receipt_id', 'sample_export_job_id', 'receiver_name', 'external_reference',
    'receipt_note', 'recorded_by', 'recorded_at',
  ])
  if (typeof item.receipt_id !== 'string' || typeof item.sample_export_job_id !== 'string'
    || typeof item.receiver_name !== 'string' || typeof item.recorded_by !== 'string'
    || typeof item.recorded_at !== 'string') throw incompatible()
  return Object.freeze({
    receiptId: item.receipt_id,
    sampleExportJobId: item.sample_export_job_id,
    receiverName: item.receiver_name,
    ...optionalStringProperty('externalReference', item.external_reference),
    ...optionalStringProperty('receiptNote', item.receipt_note),
    recordedBy: item.recorded_by,
    recordedAt: item.recorded_at,
  })
}

function parseDownloadTicket(value: JsonObject): SampleDownloadTicket {
  allowed(value, ['ticket_id', 'download_url', 'expires_at'])
  if (typeof value.ticket_id !== 'string' || typeof value.download_url !== 'string'
    || typeof value.expires_at !== 'string') throw incompatible()
  return Object.freeze({
    ticketId: value.ticket_id,
    downloadUrl: value.download_url,
    expiresAt: value.expires_at,
  })
}

function parseObjectReference(value: JsonObject): SampleObjectReference {
  allowed(value, ['bucket', 'object_key', 'sha256', 'size_bytes', 'media_type', 'object_version'])
  if (typeof value.bucket !== 'string' || typeof value.object_key !== 'string'
    || typeof value.media_type !== 'string') throw incompatible()
  if (!(value.sha256 === undefined || value.sha256 === null || typeof value.sha256 === 'string')) throw incompatible()
  if (!(value.size_bytes === undefined || value.size_bytes === null || integer(value.size_bytes))) throw incompatible()
  if (!(value.object_version === undefined || value.object_version === null || typeof value.object_version === 'string')) throw incompatible()
  return Object.freeze({
    bucket: value.bucket,
    objectKey: value.object_key,
    mediaType: value.media_type,
    ...(typeof value.sha256 === 'string' ? { sha256: value.sha256 } : {}),
    ...(typeof value.size_bytes === 'number' ? { sizeBytes: value.size_bytes } : {}),
    ...(typeof value.object_version === 'string' ? { objectVersion: value.object_version } : {}),
  })
}

function allowed(value: JsonObject, keys: readonly string[]): void {
  const allowedKeys = new Set(keys)
  if (Object.keys(value).some((key) => !allowedKeys.has(key))) throw incompatible()
}

function object(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function requireObject(value: unknown): JsonObject {
  if (!object(value)) throw incompatible()
  return value
}

function nullableString(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'string') throw incompatible()
  return value
}

function optionalStringProperty(
  property: string,
  value: unknown,
): Record<string, string> {
  const parsed = nullableString(value)
  return parsed === undefined ? {} : { [property]: parsed }
}

function integer(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function incompatible(): Error {
  return new Error('TD-CONTRACT-V2-INCOMPATIBLE-001')
}
