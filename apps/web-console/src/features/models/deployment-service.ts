import type { ApiClient } from '@/api/client'
import type {
  Acknowledgement,
  ModelDeploymentCreateRequest,
  ModelDeploymentPage as ContractModelDeploymentPage,
  ModelDeploymentSummary as ContractModelDeploymentSummary,
  RollbackRequest,
} from '@/api/generated'
import type { JsonObject } from '@/api/generated'

export type DeploymentEnvironment = 'SHADOW' | 'CANARY' | 'PRODUCTION'
export type DeploymentStrategy = 'STATION' | 'PERCENTAGE'
export type DeploymentApprovalRole = 'QUALITY_APPROVER' | 'MODEL_RELEASE_APPROVER'

export interface DeploymentView {
  readonly deployment_id: string
  readonly model_version_id: string
  readonly environment: DeploymentEnvironment
  readonly strategy: DeploymentStrategy
  readonly status: string
  readonly record_version: number
  readonly created_at: string
}

export interface AsyncAccepted {
  readonly job_id: string
  readonly status: 'QUEUED'
  readonly poll_after_ms: number
}

export interface DeploymentApprovalRequest {
  readonly role: DeploymentApprovalRole
  readonly decision: 'APPROVE' | 'REJECT'
  readonly reason: string
}

export type DeploymentSummary = ContractModelDeploymentSummary
export type DeploymentPage = ContractModelDeploymentPage

export interface DeploymentFilter {
  readonly modelVersionId?: string
  readonly status?: DeploymentSummary['status']
  readonly cursor?: string
  readonly pageSize?: number
}

export class DeploymentService {
  constructor(private readonly api: ApiClient) {}

  async list(filter: DeploymentFilter = {}): Promise<DeploymentPage> {
    const query: Record<string, string | number> = {
      page_size: filter.pageSize ?? 50,
    }
    if (filter.modelVersionId !== undefined) {
      query.model_version_id = filter.modelVersionId
    }
    if (filter.status !== undefined) query.status = filter.status
    if (filter.cursor !== undefined) query.cursor = filter.cursor
    return deploymentPage(
      await this.api.listModelDeployments({ query }),
    )
  }

  async create(request: ModelDeploymentCreateRequest): Promise<AsyncAccepted> {
    return asyncAccepted(
      await this.api.createModelDeployment({
        body: request as unknown as JsonObject,
      }),
    )
  }

  async get(deploymentId: string): Promise<DeploymentView> {
    return deploymentView(
      await this.api.getModelDeployment({
        path: { model_deployment_id: deploymentId },
      }),
    )
  }

  async approve(
    deploymentId: string,
    recordVersion: number,
    request: DeploymentApprovalRequest,
  ): Promise<Acknowledgement> {
    return acknowledgement(
      await this.api.approveModelDeployment({
        path: { model_deployment_id: deploymentId },
        headers: { 'If-Match': String(recordVersion) },
        body: request as unknown as JsonObject,
      }),
    )
  }

  async rollback(
    deploymentId: string,
    recordVersion: number,
    request: RollbackRequest,
  ): Promise<AsyncAccepted> {
    return asyncAccepted(
      await this.api.rollbackModelDeployment({
        path: { model_deployment_id: deploymentId },
        headers: { 'If-Match': String(recordVersion) },
        body: request as unknown as JsonObject,
      }),
    )
  }
}

function deploymentPage(value: JsonObject): DeploymentPage {
  exact(value, ['items', 'next_cursor', 'has_more'])
  if (
    !Array.isArray(value.items)
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')
    || typeof value.has_more !== 'boolean'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    items: Object.freeze(value.items.map(deploymentSummary)),
    next_cursor: value.next_cursor,
    has_more: value.has_more,
  }) as DeploymentPage
}

function deploymentSummary(value: unknown): DeploymentSummary {
  if (!isObject(value)) throw incompatible()
  exact(value, [
    'deployment_id',
    'model_version_id',
    'environment',
    'strategy',
    'status',
    'created_at',
  ])
  if (
    typeof value.deployment_id !== 'string'
    || typeof value.model_version_id !== 'string'
    || !isEnvironment(value.environment)
    || !isStrategy(value.strategy)
    || !['REQUESTED', 'APPROVED', 'ACTIVE', 'ROLLED_BACK', 'REJECTED']
      .includes(String(value.status))
    || typeof value.created_at !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze(value) as DeploymentSummary
}

function deploymentView(value: JsonObject): DeploymentView {
  exact(value, [
    'deployment_id',
    'model_version_id',
    'environment',
    'strategy',
    'status',
    'record_version',
    'created_at',
  ])
  if (
    typeof value.deployment_id !== 'string'
    || typeof value.model_version_id !== 'string'
    || !isEnvironment(value.environment)
    || !isStrategy(value.strategy)
    || typeof value.status !== 'string'
    || typeof value.record_version !== 'number'
    || !Number.isInteger(value.record_version)
    || value.record_version < 0
    || typeof value.created_at !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    deployment_id: value.deployment_id,
    model_version_id: value.model_version_id,
    environment: value.environment,
    strategy: value.strategy,
    status: value.status,
    record_version: value.record_version,
    created_at: value.created_at,
  })
}

function asyncAccepted(value: JsonObject): AsyncAccepted {
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

function isEnvironment(value: unknown): value is DeploymentEnvironment {
  return value === 'SHADOW' || value === 'CANARY' || value === 'PRODUCTION'
}

function isStrategy(value: unknown): value is DeploymentStrategy {
  return value === 'STATION' || value === 'PERCENTAGE'
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
