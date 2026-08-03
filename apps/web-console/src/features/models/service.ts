import type { ApiClient } from '@/api/client'
import type {
  Acknowledgement,
  ModelCreateRequest,
  ModelPage,
  ModelSummary,
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

export type ModelValidationDecisionRequest = ValidationDecisionRequest

export interface ModelVersionFilter {
  readonly cursor?: string
  readonly pageSize?: number
  readonly approvalState?: ModelApprovalState
}

export type ModelCreate = ModelCreateRequest
export type ModelCatalogPage = ModelPage
export type ModelCatalogSummary = ModelSummary

export class ModelService {
  constructor(private readonly api: ApiClient) {}

  async listModels(
    filter: Pick<ModelVersionFilter, 'cursor' | 'pageSize'> = {},
  ): Promise<ModelCatalogPage> {
    const query: Record<string, string | number> = {
      page_size: filter.pageSize ?? 50,
    }
    if (filter.cursor !== undefined) query.cursor = filter.cursor
    return modelPage(await this.api.listModels({ query }))
  }

  async createModel(request: ModelCreate): Promise<ModelCatalogSummary> {
    return modelSummary(await this.api.createModel({
      body: request as unknown as JsonObject,
    }))
  }

  async listModelVersions(
    modelId?: string,
    filter: ModelVersionFilter = {},
  ): Promise<ModelVersionPage> {
    const query: Record<string, string | number> = {
      page_size: filter.pageSize ?? 25,
    }
    if (modelId !== undefined && modelId !== '') query.model_id = modelId
    if (filter.approvalState !== undefined) {
      query.approval_state = filter.approvalState
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

function modelPage(value: JsonObject): ModelCatalogPage {
  exact(value, ['items', 'next_cursor', 'has_more'])
  if (
    !Array.isArray(value.items)
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')
    || typeof value.has_more !== 'boolean'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    items: Object.freeze(value.items.map(modelSummary)),
    next_cursor: value.next_cursor,
    has_more: value.has_more,
  }) as ModelCatalogPage
}

function modelSummary(value: unknown): ModelCatalogSummary {
  if (!isObject(value)) throw incompatible()
  exact(value, [
    'model_id',
    'model_name',
    'task_type',
    'version_count',
    'latest_version',
    'latest_approval_state',
    'created_at',
  ])
  if (
    typeof value.model_id !== 'string'
    || typeof value.model_name !== 'string'
    || typeof value.task_type !== 'string'
    || typeof value.version_count !== 'number'
    || !Number.isInteger(value.version_count)
    || !(value.latest_version === null
      || (typeof value.latest_version === 'number'
        && Number.isInteger(value.latest_version)))
    || !(value.latest_approval_state === null
      || APPROVAL_STATES.has(value.latest_approval_state as ModelApprovalState))
    || typeof value.created_at !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze(value) as ModelCatalogSummary
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

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function incompatible(): Error {
  return new Error('TD-CONTRACT-INCOMPATIBLE-001')
}
