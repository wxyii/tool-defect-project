import type { ApiClient } from '@/api/client'
import type { TrainingRunCreateRequest } from '@/api/generated'
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

export class TrainingService {
  constructor(private readonly api: ApiClient) {}

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
