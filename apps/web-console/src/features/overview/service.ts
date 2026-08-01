import type { ApiClient } from '@/api/client'
import type { JsonObject, SystemOverview } from '@/api/generated'

export type { SystemOverview }

export class OverviewService {
  constructor(private readonly api: ApiClient) {}

  async get(): Promise<SystemOverview> {
    return parseSystemOverview(await this.api.getSystemOverview())
  }
}

export function parseSystemOverview(value: JsonObject): SystemOverview {
  exact(value, [
    'generated_at',
    'window',
    'captures',
    'reviews',
    'fleet',
    'inference',
    'model_runtime',
    'outcome_comparison',
    'quality_comparison',
  ])
  timestamp(value.generated_at)

  const window = object(value.window)
  exact(window, [
    'timezone',
    'current_start',
    'current_end',
    'previous_start',
    'previous_end',
  ])
  text(window.timezone, 64)
  timestamp(window.current_start)
  timestamp(window.current_end)
  timestamp(window.previous_start)
  timestamp(window.previous_end)

  integers(object(value.captures), [
    'total', 'pass', 'fail', 'hold', 'unresolved',
  ])
  integers(object(value.reviews), [
    'total',
    'pending',
    'claimed',
    'second_review_pending',
    'escalated',
    'oldest_age_seconds',
  ])

  const fleet = object(value.fleet)
  integers(fleet, [
    'stations_total',
    'stations_online',
    'stations_maintenance',
    'devices_total',
    'devices_online',
    'devices_degraded',
    'devices_offline',
    'heartbeat_freshness_seconds',
  ])
  if ((fleet.heartbeat_freshness_seconds as number) < 1) throw incompatible()

  const inference = object(value.inference)
  exact(inference, [
    'queued',
    'running',
    'retry_wait',
    'dead',
    'failures_24h',
    'completed_in_window',
    'p95_duration_ms',
  ])
  for (const field of [
    'queued',
    'running',
    'retry_wait',
    'dead',
    'failures_24h',
    'completed_in_window',
  ]) {
    nonNegativeInteger(inference[field])
  }
  nullableNonNegative(inference.p95_duration_ms)

  const runtime = object(value.model_runtime)
  exact(runtime, [
    'production',
    'active_shadow_deployments',
    'active_canary_deployments',
    'canary_traffic_ratio',
  ])
  nonNegativeInteger(runtime.active_shadow_deployments)
  nonNegativeInteger(runtime.active_canary_deployments)
  ratio(runtime.canary_traffic_ratio)
  if (runtime.production !== null) {
    const production = object(runtime.production)
    exact(production, [
      'deployment_id',
      'model_version_id',
      'registry_name',
      'registry_version',
      'traffic_ratio',
      'effective_at',
    ])
    uuid(production.deployment_id)
    uuid(production.model_version_id)
    nullableText(production.registry_name, 256)
    nullableText(production.registry_version, 128)
    ratio(production.traffic_ratio)
    if (production.effective_at !== null) timestamp(production.effective_at)
  }

  comparison(value.outcome_comparison, [
    'qualified', 'unqualified', 'inconclusive',
  ])
  comparison(value.quality_comparison, ['ok', 'warning', 'rejected'])
  return deepFreeze(value) as unknown as SystemOverview
}

function comparison(value: unknown, fields: readonly string[]): void {
  const target = object(value)
  exact(target, ['current', 'previous'])
  integers(object(target.current), fields)
  integers(object(target.previous), fields)
}

function integers(value: JsonObject, fields: readonly string[]): void {
  exact(value, fields)
  for (const field of fields) nonNegativeInteger(value[field])
}

function nonNegativeInteger(value: unknown): void {
  if (
    typeof value !== 'number'
    || !Number.isInteger(value)
    || value < 0
  ) {
    throw incompatible()
  }
}

function nullableNonNegative(value: unknown): void {
  if (
    value !== null
    && (typeof value !== 'number' || !Number.isFinite(value) || value < 0)
  ) {
    throw incompatible()
  }
}

function ratio(value: unknown): void {
  if (
    typeof value !== 'number'
    || !Number.isFinite(value)
    || value < 0
    || value > 1
  ) {
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
