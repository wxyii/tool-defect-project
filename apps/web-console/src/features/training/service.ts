import type { ApiClient } from '@/api/client'
import type {
  TrainingRunCreateRequest,
  TrainingRunPage as ContractTrainingRunPage,
  TrainingRunSummary as ContractTrainingRunSummary,
} from '@/api/generated'
import type { JsonObject } from '@/api/generated'

export interface TrainingRunView {
  readonly id: string
  readonly version: string
  readonly status: string
  readonly created_at: string
}

export interface TrainingAccepted {
  readonly job_id: string
  readonly status: 'QUEUED'
  readonly poll_after_ms: number
}

export type TrainingRunSummary = ContractTrainingRunSummary
export type TrainingRunPage = ContractTrainingRunPage

export interface TrainingRunFilter {
  readonly status?: TrainingRunSummary['status']
  readonly cursor?: string
  readonly pageSize?: number
}

export class TrainingService {
  constructor(private readonly api: ApiClient) {}

  async list(filter: TrainingRunFilter = {}): Promise<TrainingRunPage> {
    const query: Record<string, string | number> = {
      page_size: filter.pageSize ?? 50,
    }
    if (filter.status !== undefined) query.status = filter.status
    if (filter.cursor !== undefined) query.cursor = filter.cursor
    return trainingRunPage(await this.api.listTrainingRuns({ query }))
  }

  async create(request: TrainingRunCreateRequest): Promise<TrainingAccepted> {
    return accepted(
      await this.api.createTrainingRun({
        body: request as unknown as JsonObject,
      }),
    )
  }

  async get(trainingRunId: string): Promise<TrainingRunView> {
    return trainingRun(
      await this.api.getTrainingRun({
        path: { training_run_id: trainingRunId },
      }),
    )
  }
}

function trainingRunPage(value: JsonObject): TrainingRunPage {
  exact(value, ['items', 'next_cursor', 'has_more'])
  if (
    !Array.isArray(value.items)
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')
    || typeof value.has_more !== 'boolean'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    items: Object.freeze(value.items.map(trainingRunSummary)),
    next_cursor: value.next_cursor,
    has_more: value.has_more,
  }) as TrainingRunPage
}

function trainingRunSummary(value: unknown): TrainingRunSummary {
  if (!isObject(value)) throw incompatible()
  exact(value, [
    'training_run_id',
    'dataset_version_id',
    'training_config_version',
    'initial_model_version_id',
    'status',
    'failure_code',
    'started_at',
    'finished_at',
    'created_at',
  ])
  if (
    typeof value.training_run_id !== 'string'
    || typeof value.dataset_version_id !== 'string'
    || typeof value.training_config_version !== 'string'
    || !(value.initial_model_version_id === null
      || typeof value.initial_model_version_id === 'string')
    || !['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED']
      .includes(String(value.status))
    || !(value.failure_code === null || typeof value.failure_code === 'string')
    || !(value.started_at === null || typeof value.started_at === 'string')
    || !(value.finished_at === null || typeof value.finished_at === 'string')
    || typeof value.created_at !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze(value) as TrainingRunSummary
}

function trainingRun(value: JsonObject): TrainingRunView {
  exact(value, ['id', 'version', 'status', 'created_at'])
  if (
    typeof value.id !== 'string'
    || typeof value.version !== 'string'
    || typeof value.status !== 'string'
    || typeof value.created_at !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    id: value.id,
    version: value.version,
    status: value.status,
    created_at: value.created_at,
  })
}

function accepted(value: JsonObject): TrainingAccepted {
  exact(value, ['job_id', 'status', 'poll_after_ms'])
  if (
    typeof value.job_id !== 'string'
    || value.status !== 'QUEUED'
    || typeof value.poll_after_ms !== 'number'
    || !Number.isInteger(value.poll_after_ms)
    || value.poll_after_ms < 100
    || value.poll_after_ms > 60000
  ) {
    throw incompatible()
  }
  return Object.freeze({
    job_id: value.job_id,
    status: 'QUEUED',
    poll_after_ms: value.poll_after_ms,
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

function incompatible(): Error {
  return new Error('TD-CONTRACT-INCOMPATIBLE-001')
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
