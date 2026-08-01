import type { ApiClient } from '@/api/client'
import type {
  AsyncAccepted,
  DatasetApprovalRequest,
  DatasetCandidateManifestApprovalResponse,
  DatasetCandidateManifestPage as ContractDatasetCandidateManifestPage,
  DatasetCandidateManifestSummary as ContractDatasetCandidateManifestSummary,
  DatasetCreateRequest,
  DatasetPage,
  DatasetSummary,
  DatasetVersionApprovalResponse,
  DatasetVersionCreateRequest,
  DatasetVersionDiff as ContractDatasetVersionDiff,
  DatasetVersionDiffItem as ContractDatasetVersionDiffItem,
  DatasetVersionPage as ContractDatasetVersionPage,
  DatasetVersionSummary as ContractDatasetVersionSummary,
  JsonObject,
  VersionedResource,
} from '@/api/generated'

export interface DatasetVersionFilter {
  readonly cursor?: string
  readonly pageSize?: number
}

export interface DatasetCatalogFilter extends DatasetVersionFilter {
  readonly datasetId?: string
  readonly status?: DatasetVersionSummary['status']
}

export type DatasetCreate = DatasetCreateRequest
export type DatasetCatalogPage = DatasetPage
export type DatasetCatalogSummary = DatasetSummary

export type DatasetVersionSummary = ContractDatasetVersionSummary
export type DatasetVersionPage = ContractDatasetVersionPage
export type DatasetCandidateManifestSummary = ContractDatasetCandidateManifestSummary
export type DatasetCandidateManifestPage = ContractDatasetCandidateManifestPage
export type DatasetBuildAccepted = AsyncAccepted
export type DatasetApproval = DatasetApprovalRequest
export type CandidateManifestApproval = DatasetCandidateManifestApprovalResponse
export type VersionApproval = DatasetVersionApprovalResponse
export type VersionDiff = ContractDatasetVersionDiff
export type VersionDiffItem = ContractDatasetVersionDiffItem

export class DatasetService {
  constructor(private readonly api: ApiClient) {}

  async listDatasets(
    filter: DatasetVersionFilter = {},
  ): Promise<DatasetCatalogPage> {
    const query: Record<string, string | number> = {
      page_size: filter.pageSize ?? 50,
    }
    if (filter.cursor !== undefined) query.cursor = filter.cursor
    return datasetPage(await this.api.listDatasets({ query }))
  }

  async createDataset(request: DatasetCreate): Promise<DatasetCatalogSummary> {
    return datasetSummary(await this.api.createDataset({
      body: request as unknown as JsonObject,
    }))
  }

  async listVersionCatalog(
    filter: DatasetCatalogFilter = {},
  ): Promise<DatasetVersionPage> {
    const query: Record<string, string | number> = {
      page_size: filter.pageSize ?? 50,
    }
    if (filter.datasetId !== undefined) query.dataset_id = filter.datasetId
    if (filter.status !== undefined) query.status = filter.status
    if (filter.cursor !== undefined) query.cursor = filter.cursor
    return datasetVersionPage(
      await this.api.listDatasetVersionCatalog({ query }),
    )
  }

  async listVersions(
    datasetId: string,
    filter: DatasetVersionFilter = {},
  ): Promise<DatasetVersionPage> {
    const query: Record<string, string | number> = {
      page_size: filter.pageSize ?? 25,
    }
    if (filter.cursor !== undefined) query.cursor = filter.cursor
    return datasetVersionPage(
      await this.api.listDatasetVersions({
        path: { dataset_id: datasetId },
        query,
      }),
    )
  }

  async listCandidateManifests(
    datasetId: string,
    filter: DatasetVersionFilter = {},
  ): Promise<DatasetCandidateManifestPage> {
    const query: Record<string, string | number> = {
      dataset_id: datasetId,
      page_size: filter.pageSize ?? 50,
    }
    if (filter.cursor !== undefined) query.cursor = filter.cursor
    return candidateManifestPage(
      await this.api.listDatasetCandidateManifests({ query }),
    )
  }

  async createVersion(
    request: DatasetVersionCreateRequest,
  ): Promise<DatasetBuildAccepted> {
    return buildAccepted(await this.api.createDatasetVersion({
      body: request as unknown as JsonObject,
    }))
  }

  async approveCandidateManifest(
    candidateManifestId: string,
    request: DatasetApproval,
  ): Promise<CandidateManifestApproval> {
    return candidateManifestApproval(
      await this.api.approveDatasetCandidateManifest({
        path: { candidate_manifest_id: candidateManifestId },
        body: request as unknown as JsonObject,
      }),
    )
  }

  async approveVersion(
    datasetVersionId: string,
    request: DatasetApproval,
  ): Promise<VersionApproval> {
    return versionApproval(await this.api.approveDatasetVersion({
      path: { dataset_version_id: datasetVersionId },
      body: request as unknown as JsonObject,
    }))
  }

  async detailVersion(versionId: string): Promise<VersionedResource> {
    return versionedResource(
      await this.api.getDatasetVersion({
        path: { dataset_version_id: versionId },
      }),
    )
  }

  async diffVersions(
    fromVersionId: string,
    toVersionId: string,
  ): Promise<VersionDiff> {
    return versionDiff(
      await this.api.diffDatasetVersions({
        query: { from: fromVersionId, to: toVersionId },
      }),
    )
  }
}

function datasetPage(value: JsonObject): DatasetCatalogPage {
  exact(value, ['items', 'next_cursor', 'has_more'])
  if (
    !Array.isArray(value.items)
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')
    || typeof value.has_more !== 'boolean'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    items: Object.freeze(value.items.map(datasetSummary)),
    next_cursor: value.next_cursor,
    has_more: value.has_more,
  }) as DatasetCatalogPage
}

function datasetSummary(value: unknown): DatasetCatalogSummary {
  if (!isObject(value)) throw incompatible()
  exact(value, [
    'dataset_id',
    'dataset_name',
    'purpose',
    'version_count',
    'latest_version',
    'latest_status',
    'created_at',
  ])
  if (
    typeof value.dataset_id !== 'string'
    || typeof value.dataset_name !== 'string'
    || typeof value.purpose !== 'string'
    || typeof value.version_count !== 'number'
    || !Number.isInteger(value.version_count)
    || !(value.latest_version === null || typeof value.latest_version === 'string')
    || !(
      value.latest_status === null
      || ['BUILDING', 'VALIDATING', 'FROZEN', 'REJECTED']
        .includes(String(value.latest_status))
    )
    || typeof value.created_at !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    dataset_id: value.dataset_id,
    dataset_name: value.dataset_name,
    purpose: value.purpose,
    version_count: value.version_count,
    latest_version: value.latest_version,
    latest_status: value.latest_status,
    created_at: value.created_at,
  }) as DatasetCatalogSummary
}

function datasetVersionPage(value: JsonObject): DatasetVersionPage {
  exact(value, ['items', 'next_cursor', 'has_more'])
  if (
    !Array.isArray(value.items)
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')
    || typeof value.has_more !== 'boolean'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    items: Object.freeze(value.items.map(datasetVersionSummary)),
    next_cursor: value.next_cursor,
    has_more: value.has_more,
  }) as DatasetVersionPage
}

function candidateManifestPage(value: JsonObject): DatasetCandidateManifestPage {
  exact(value, ['items', 'next_cursor', 'has_more'])
  if (
    !Array.isArray(value.items)
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')
    || typeof value.has_more !== 'boolean'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    items: Object.freeze(value.items.map(candidateManifestSummary)),
    next_cursor: value.next_cursor,
    has_more: value.has_more,
  }) as DatasetCandidateManifestPage
}

function candidateManifestSummary(
  value: unknown,
): DatasetCandidateManifestSummary {
  if (!isObject(value)) throw incompatible()
  exact(value, [
    'candidate_manifest_id',
    'dataset_id',
    'manifest_bucket',
    'manifest_object_key',
    'manifest_sha256',
    'sample_count',
    'approval_state',
    'approved_by',
    'approved_at',
    'created_at',
  ])
  if (
    typeof value.candidate_manifest_id !== 'string'
    || typeof value.dataset_id !== 'string'
    || typeof value.manifest_bucket !== 'string'
    || typeof value.manifest_object_key !== 'string'
    || typeof value.manifest_sha256 !== 'string'
    || typeof value.sample_count !== 'number'
    || !Number.isInteger(value.sample_count)
    || !['REGISTERED', 'APPROVED', 'REJECTED']
      .includes(String(value.approval_state))
    || !(value.approved_by === null || typeof value.approved_by === 'string')
    || !(value.approved_at === null || typeof value.approved_at === 'string')
    || typeof value.created_at !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze(value) as DatasetCandidateManifestSummary
}

function buildAccepted(value: JsonObject): DatasetBuildAccepted {
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
  }) as DatasetBuildAccepted
}

function candidateManifestApproval(
  value: JsonObject,
): CandidateManifestApproval {
  exact(value, [
    'candidate_manifest_id',
    'approval_state',
    'approved_by',
    'approved_at',
    'message',
  ])
  if (
    typeof value.candidate_manifest_id !== 'string'
    || !['APPROVED', 'REJECTED'].includes(String(value.approval_state))
    || !(value.approved_by === null || typeof value.approved_by === 'string')
    || !(value.approved_at === null || typeof value.approved_at === 'string')
    || typeof value.message !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze(value) as CandidateManifestApproval
}

function versionApproval(value: JsonObject): VersionApproval {
  exact(value, [
    'dataset_version_id',
    'version',
    'state',
    'approved_at',
    'message',
  ])
  if (
    typeof value.dataset_version_id !== 'string'
    || typeof value.version !== 'string'
    || !['FROZEN', 'REJECTED'].includes(String(value.state))
    || !(value.approved_at === null || typeof value.approved_at === 'string')
    || typeof value.message !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze(value) as VersionApproval
}

function datasetVersionSummary(value: unknown): DatasetVersionSummary {
  if (!isObject(value)) throw incompatible()
  exact(value, [
    'version_id',
    'dataset_id',
    'version',
    'sample_count',
    'status',
    'manifest_sha256',
    'created_at',
  ])
  if (
    typeof value.version_id !== 'string'
    || typeof value.dataset_id !== 'string'
    || typeof value.version !== 'string'
    || typeof value.sample_count !== 'number'
    || !Number.isInteger(value.sample_count)
    || !['BUILDING', 'VALIDATING', 'FROZEN', 'REJECTED'].includes(String(value.status))
    || !(value.manifest_sha256 === null || typeof value.manifest_sha256 === 'string')
    || typeof value.created_at !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    version_id: value.version_id,
    dataset_id: value.dataset_id,
    version: value.version,
    sample_count: value.sample_count,
    status: value.status,
    manifest_sha256: value.manifest_sha256,
    created_at: value.created_at,
  }) as DatasetVersionSummary
}

function versionedResource(value: JsonObject): VersionedResource {
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
  }) as VersionedResource
}

function versionDiff(value: JsonObject): VersionDiff {
  exact(value, [
    'from_version',
    'to_version',
    'added_samples',
    'removed_samples',
    'modified_samples',
    'unchanged_samples',
    'sample_diff_details',
  ])
  if (
    !isObject(value.from_version)
    || !isObject(value.to_version)
    || typeof value.added_samples !== 'number'
    || !Number.isInteger(value.added_samples)
    || typeof value.removed_samples !== 'number'
    || !Number.isInteger(value.removed_samples)
    || typeof value.modified_samples !== 'number'
    || !Number.isInteger(value.modified_samples)
    || typeof value.unchanged_samples !== 'number'
    || !Number.isInteger(value.unchanged_samples)
    || !Array.isArray(value.sample_diff_details)
  ) {
    throw incompatible()
  }
  return Object.freeze({
    from_version: datasetVersionSummary(value.from_version),
    to_version: datasetVersionSummary(value.to_version),
    added_samples: value.added_samples,
    removed_samples: value.removed_samples,
    modified_samples: value.modified_samples,
    unchanged_samples: value.unchanged_samples,
    sample_diff_details: Object.freeze(
      value.sample_diff_details.map(diffItem),
    ),
  }) as VersionDiff
}

function diffItem(value: unknown): VersionDiffItem {
  if (!isObject(value)) throw incompatible()
  exact(value, ['sample_id', 'change', 'diff_summary'])
  if (
    typeof value.sample_id !== 'string'
    || !['ADDED', 'REMOVED', 'MODIFIED', 'UNCHANGED'].includes(String(value.change))
    || typeof value.diff_summary !== 'string'
  ) {
    throw incompatible()
  }
  return Object.freeze({
    sample_id: value.sample_id,
    change: value.change,
    diff_summary: value.diff_summary,
  }) as VersionDiffItem
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
