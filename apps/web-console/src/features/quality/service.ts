import type { ApiClient } from '@/api/client'
import type {
  JsonObject,
  QualityMetrics,
} from '@/api/generated'

export type { QualityMetrics }

export interface QualityFilter {
  readonly startDate?: string
  readonly endDate?: string
  readonly modelVersionId?: string
}

export class QualityService {
  constructor(private readonly api: ApiClient) {}

  async getMetrics(filter: QualityFilter = {}): Promise<QualityMetrics> {
    const query: Record<string, string> = {}
    if (filter.startDate !== undefined) query.start_date = filter.startDate
    if (filter.endDate !== undefined) query.end_date = filter.endDate
    if (filter.modelVersionId !== undefined) query.model_version_id = filter.modelVersionId
    return qualityMetrics(
      await this.api.getQualityMetrics({ query }),
    )
  }
}

function qualityMetrics(value: JsonObject): QualityMetrics {
  exact(value, [
    'time_window',
    'auto_pass_fail_rate',
    'model_overturn_rate',
    'missed_detection_count',
    'false_positive_count',
    'mask_revision_reasons',
    'total_sample_count',
    'based_on_full_ground_truth',
  ])
  if (
    !isObject(value.time_window)
    || typeof value.auto_pass_fail_rate !== 'number'
    || typeof value.model_overturn_rate !== 'number'
    || typeof value.missed_detection_count !== 'number'
    || !Number.isInteger(value.missed_detection_count)
    || typeof value.false_positive_count !== 'number'
    || !Number.isInteger(value.false_positive_count)
    || !Array.isArray(value.mask_revision_reasons)
    || typeof value.total_sample_count !== 'number'
    || !Number.isInteger(value.total_sample_count)
    || typeof value.based_on_full_ground_truth !== 'boolean'
  ) {
    throw incompatible()
  }
  const tw = value.time_window
  if (!isUtcTimestamp(tw.start) || !isUtcTimestamp(tw.end)) {
    throw incompatible()
  }
  return Object.freeze({
    time_window: Object.freeze({ start: tw.start, end: tw.end }),
    auto_pass_fail_rate: value.auto_pass_fail_rate,
    model_overturn_rate: value.model_overturn_rate,
    missed_detection_count: value.missed_detection_count,
    false_positive_count: value.false_positive_count,
    mask_revision_reasons: Object.freeze(value.mask_revision_reasons.map(maskRevisionReason)),
    total_sample_count: value.total_sample_count,
    based_on_full_ground_truth: value.based_on_full_ground_truth,
  })
}

function maskRevisionReason(value: JsonObject): QualityMetrics['mask_revision_reasons'][number] {
  exact(value, ['reason', 'count', 'percentage'])
  if (
    typeof value.reason !== 'string'
    || typeof value.count !== 'number'
    || !Number.isInteger(value.count)
    || typeof value.percentage !== 'number'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    reason: value.reason,
    count: value.count,
    percentage: value.percentage,
  })
}

function exact(value: JsonObject, keys: readonly string[]): void {
  if (
    Object.keys(value).length !== keys.length
    || Object.keys(value).some((key) => !keys.includes(key))
  ) {
    throw incompatible()
  }
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isUtcTimestamp(value: unknown): value is `${string}Z` {
  return typeof value === 'string' && value.endsWith('Z')
}

function incompatible(): Error {
  return new Error('TD-CONTRACT-INCOMPATIBLE-001')
}
