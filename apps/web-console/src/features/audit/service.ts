import type { ApiClient } from '@/api/client'
import type {
  AuditRecordPage,
  AuditRecordSummary,
  JsonObject,
} from '@/api/generated'

export type { AuditRecordPage, AuditRecordSummary }

export interface AuditFilters {
  readonly cursor?: string
  readonly pageSize?: number
  readonly startTime?: string
  readonly endTime?: string
  readonly actorId?: string
  readonly action?: string
  readonly resourceType?: string
  readonly resourceId?: string
  readonly result?: string
}

export class AuditService {
  constructor(private readonly api: ApiClient) {}

  async list(filters: AuditFilters = {}): Promise<AuditRecordPage> {
    const query: Record<string, string | number> = {
      page_size: filters.pageSize ?? 50,
    }
    optional(query, 'cursor', filters.cursor)
    optional(query, 'start_time', filters.startTime)
    optional(query, 'end_time', filters.endTime)
    optional(query, 'actor_id', filters.actorId)
    optional(query, 'action', filters.action)
    optional(query, 'resource_type', filters.resourceType)
    optional(query, 'resource_id', filters.resourceId)
    optional(query, 'result', filters.result)
    return parseAuditRecordPage(
      await this.api.listAuditRecords({ query }),
    )
  }
}

export function parseAuditRecordPage(value: JsonObject): AuditRecordPage {
  exact(value, ['items', 'next_cursor', 'has_more'])
  if (
    !Array.isArray(value.items)
    || value.items.length > 200
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')
    || typeof value.has_more !== 'boolean'
  ) {
    throw incompatible()
  }
  for (const item of value.items) auditRecord(item)
  return deepFreeze(value) as unknown as AuditRecordPage
}

function auditRecord(value: unknown): void {
  const item = object(value)
  exact(item, [
    'audit_id',
    'occurred_at',
    'actor_type',
    'actor_id',
    'actor_ip',
    'action',
    'resource_type',
    'resource_id',
    'before_digest',
    'after_digest',
    'reason',
    'request_id',
    'trace_id',
    'result',
    'error_code',
  ])
  uuid(item.audit_id)
  timestamp(item.occurred_at)
  text(item.actor_type, 24)
  text(item.actor_id, 256)
  nullableText(item.actor_ip, 64)
  text(item.action, 128)
  text(item.resource_type, 128)
  text(item.resource_id, 256)
  nullableSha256(item.before_digest)
  nullableSha256(item.after_digest)
  nullableText(item.reason, 2048)
  text(item.request_id, 128)
  if (typeof item.trace_id !== 'string' || !/^[0-9a-f]{32}$/.test(item.trace_id)) {
    throw incompatible()
  }
  text(item.result, 24)
  nullableText(item.error_code, 64)
}

function optional(
  query: Record<string, string | number>,
  field: string,
  value: string | undefined,
): void {
  if (value !== undefined && value.trim() !== '') query[field] = value.trim()
}

function nullableSha256(value: unknown): void {
  if (value !== null && (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value))) {
    throw incompatible()
  }
}

function text(value: unknown, maximum: number): asserts value is string {
  if (typeof value !== 'string' || value.length < 1 || value.length > maximum) {
    throw incompatible()
  }
}

function nullableText(value: unknown, maximum: number): void {
  if (value !== null) text(value, maximum)
}

function timestamp(value: unknown): void {
  if (
    typeof value !== 'string'
    || !value.endsWith('Z')
    || !Number.isFinite(Date.parse(value))
  ) {
    throw incompatible()
  }
}

function uuid(value: unknown): void {
  if (
    typeof value !== 'string'
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
  ) {
    throw incompatible()
  }
}

function object(value: unknown): JsonObject {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw incompatible()
  }
  return value as JsonObject
}

function exact(value: JsonObject, fields: readonly string[]): void {
  if (
    Object.keys(value).length !== fields.length
    || Object.keys(value).some((field) => !fields.includes(field))
  ) {
    throw incompatible()
  }
}

function deepFreeze(value: unknown): unknown {
  if (typeof value !== 'object' || value === null || Object.isFrozen(value)) {
    return value
  }
  for (const child of Object.values(value)) deepFreeze(child)
  return Object.freeze(value)
}

function incompatible(): Error {
  return new Error('TD-CONTRACT-INCOMPATIBLE-001')
}
