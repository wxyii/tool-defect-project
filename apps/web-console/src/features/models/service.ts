import type { ApiClient } from '@/api/client'
import type {
  Acknowledgement,
  ModelVersionRegisterRequest,
  ModelVersionRegistrationResponse,
  ValidationDecisionRequest,
} from '@/api/generated'
import type { JsonObject } from '@/api/generated'

export type ModelApprovalState =
  | 'CANDIDATE'
  | 'VALIDATED'
  | 'APPROVED'
  | 'REJECTED'
  | 'RETIRED'

const APPROVAL_STATES = new Set<ModelApprovalState>([
  'CANDIDATE',
  'VALIDATED',
  'APPROVED',
  'REJECTED',
  'RETIRED',
])

export interface ModelVersionSummary {
  readonly model_version_id: string
  readonly model_id: string
  readonly version: number
  readonly registry_name: string
  readonly registry_version: string
  readonly approval_state: ModelApprovalState
  readonly created_at: string
}

export type ModelVersionDetail = ModelVersionSummary & {
  readonly artifact_sha256: string
}

export interface ModelVersionPage {
  readonly items: readonly ModelVersionSummary[]
  readonly next_cursor: string | null
  readonly has_more: boolean
}

export type RegisterModelVersionRequest = ModelVersionRegisterRequest
export type ModelRegistrationResponse = ModelVersionRegistrationResponse
export type ModelValidationDecisionRequest = ValidationDecisionRequest

export interface ModelVersionFilter {
  readonly cursor?: string
  readonly pageSize?: number
}

export class ModelService {
  constructor(private readonly api: ApiClient) {}

  async listModelVersions(
    modelId: string,
    filter: ModelVersionFilter = {},
  ): Promise<ModelVersionPage> {
    const query: Record<string, string | number> = {
      model_id: modelId,
      page_size: filter.pageSize ?? 25,
    }
    if (filter.cursor !== undefined) query.cursor = filter.cursor
    return modelVersionPage(
      await this.api.listModelVersions({ query }),
    )
  }

  async detailModelVersion(versionId: string): Promise<ModelVersionDetail> {
    return modelVersionDetail(
      await this.api.getModelVersion({
        path: { model_version_id: versionId },
      }),
    )
  }

  async registerModelVersion(
    request: RegisterModelVersionRequest,
  ): Promise<ModelRegistrationResponse> {
    return registrationResponse(
      await this.api.registerModelVersion({
        body: request as unknown as JsonObject,
      }),
    )
  }

  async submitValidationDecision(
    versionId: string,
    decision: ModelValidationDecisionRequest,
  ): Promise<Acknowledgement> {
    return acknowledgement(
      await this.api.submitModelValidationDecision({
        path: { model_version_id: versionId },
        body: decision as unknown as JsonObject,
      }),
    )
  }
}

function modelVersionPage(value: JsonObject): ModelVersionPage {
  exact(value, ['items', 'next_cursor', 'has_more'])
  if (
    !Array.isArray(value.items)
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')
    || typeof value.has_more !== 'boolean'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    items: Object.freeze(
      value.items.map((item: JsonObject) => modelVersionSummary(item)),
    ),
    next_cursor: value.next_cursor,
    has_more: value.has_more,
  })
}

function modelVersionSummary(value: JsonObject): ModelVersionSummary {
  exact(value, [
    'model_version_id',
    'model_id',
    'version',
    'registry_name',
    'registry_version',
    'approval_state',
    'created_at',
  ])
  const state = approvalState(value.approval_state)
  if (
    typeof value.model_version_id !== 'string'
    || typeof value.model_id !== 'string'
    || typeof value.version !== 'number'
    || !Number.isInteger(value.version)
    || typeof value.registry_name !== 'string'
    || typeof value.registry_version !== 'string'
    || state === null
    || typeof value.created_at !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    model_version_id: value.model_version_id,
    model_id: value.model_id,
    version: value.version,
    registry_name: value.registry_name,
    registry_version: value.registry_version,
    approval_state: state,
    created_at: value.created_at,
  })
}

function modelVersionDetail(value: JsonObject): ModelVersionDetail {
  exact(value, [
    'model_version_id',
    'model_id',
    'version',
    'registry_name',
    'registry_version',
    'artifact_sha256',
    'approval_state',
    'created_at',
  ])
  const summary = modelVersionSummary({
    model_version_id: value.model_version_id,
    model_id: value.model_id,
    version: value.version,
    registry_name: value.registry_name,
    registry_version: value.registry_version,
    approval_state: value.approval_state,
    created_at: value.created_at,
  })
  if (typeof value.artifact_sha256 !== 'string') throw incompatible()
  return Object.freeze({ ...summary, artifact_sha256: value.artifact_sha256 })
}

function registrationResponse(value: JsonObject): ModelRegistrationResponse {
  exact(value, ['model_version_id', 'version', 'approval_state', 'created_at'])
  const state = approvalState(value.approval_state)
  if (
    typeof value.model_version_id !== 'string'
    || typeof value.version !== 'number'
    || !Number.isInteger(value.version)
    || state === null
    || typeof value.created_at !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    model_version_id: value.model_version_id as ModelRegistrationResponse['model_version_id'],
    version: value.version,
    approval_state: state,
    created_at: value.created_at as ModelRegistrationResponse['created_at'],
  })
}

function acknowledgement(value: JsonObject): Acknowledgement {
  exact(value, ['accepted', 'request_id'])
  if (typeof value.accepted !== 'boolean' || typeof value.request_id !== 'string') {
    throw incompatible()
  }
  return Object.freeze({
    accepted: value.accepted,
    request_id: value.request_id as Acknowledgement['request_id'],
  })
}

function approvalState(value: unknown): ModelApprovalState | null {
  return typeof value === 'string' && APPROVAL_STATES.has(value as ModelApprovalState)
    ? value as ModelApprovalState
    : null
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
