import { describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '@/api/client'
import { DatasetService } from '@/features/datasets/service'
import { DeploymentService } from '@/features/models/deployment-service'
import {
  buildModelRegistrationRequest,
  ModelRegistrationInputError,
} from '@/features/models/registration'
import { ModelService } from '@/features/models/service'
import { TrainingService } from '@/features/training/service'
import { hasRouteAccess } from '@/router/access'
import { applicationRoutes } from '@/router/routes'

const modelVersionId = '019f0000-0000-7000-8000-000000000001'
const modelId = '019f0000-0000-7000-8000-000000000002'
const trainingRunId = '019f0000-0000-7000-8000-000000000003'
const datasetId = '019f0000-0000-7000-8000-000000000006'
const datasetVersionId = '019f0000-0000-7000-8000-000000000007'
const candidateManifestId = '019f0000-0000-7000-8000-000000000008'

function fakeApi(): ApiClient {
  return {
    listDatasets: vi.fn().mockResolvedValue({
      items: [{
        dataset_id: datasetId,
        dataset_name: '生产候选集',
        purpose: '增量训练',
        version_count: 1,
        latest_version: '1',
        latest_status: 'FROZEN',
        created_at: '2026-07-31T09:00:00.000Z',
      }],
      next_cursor: null,
      has_more: false,
    }),
    createDataset: vi.fn().mockResolvedValue({
      dataset_id: datasetId,
      dataset_name: '生产候选集',
      purpose: '增量训练',
      version_count: 0,
      latest_version: null,
      latest_status: null,
      created_at: '2026-07-31T09:00:00.000Z',
    }),
    listDatasetCandidateManifests: vi.fn().mockResolvedValue({
      items: [{
        candidate_manifest_id: candidateManifestId,
        dataset_id: datasetId,
        manifest_bucket: 'td-datasets',
        manifest_object_key: 'candidate/production-v1/manifest.csv',
        manifest_sha256: 'b'.repeat(64),
        sample_count: 172,
        approval_state: 'APPROVED',
        approved_by: '019f0000-0000-7000-8000-000000000009',
        approved_at: '2026-07-31T09:20:00.000Z',
        created_at: '2026-07-31T09:10:00.000Z',
      }],
      next_cursor: null,
      has_more: false,
    }),
    createDatasetVersion: vi.fn().mockResolvedValue({
      job_id: datasetVersionId,
      status: 'QUEUED',
      poll_after_ms: 1000,
    }),
    approveDatasetCandidateManifest: vi.fn().mockResolvedValue({
      candidate_manifest_id: candidateManifestId,
      approval_state: 'APPROVED',
      approved_by: '019f0000-0000-7000-8000-000000000009',
      approved_at: '2026-07-31T09:20:00.000Z',
      message: '候选清单已批准',
    }),
    approveDatasetVersion: vi.fn().mockResolvedValue({
      dataset_version_id: datasetVersionId,
      version: '1',
      state: 'FROZEN',
      approved_at: '2026-07-31T09:40:00.000Z',
      message: '数据集版本已冻结',
    }),
    listDatasetVersionCatalog: vi.fn().mockResolvedValue({
      items: [{
        version_id: datasetVersionId,
        dataset_id: datasetId,
        version: '1',
        sample_count: 172,
        status: 'FROZEN',
        manifest_sha256: 'a'.repeat(64),
        created_at: '2026-07-31T09:30:00.000Z',
      }],
      next_cursor: null,
      has_more: false,
    }),
    listTrainingRuns: vi.fn().mockResolvedValue({
      items: [{
        training_run_id: trainingRunId,
        dataset_version_id: datasetVersionId,
        training_config_version: 'multitask/1.0.0',
        initial_model_version_id: null,
        status: 'QUEUED',
        failure_code: null,
        started_at: null,
        finished_at: null,
        created_at: '2026-07-31T10:00:00.000Z',
      }],
      next_cursor: null,
      has_more: false,
    }),
    listModels: vi.fn().mockResolvedValue({
      items: [{
        model_id: modelId,
        model_name: '多任务模型',
        task_type: 'classification-segmentation',
        version_count: 1,
        latest_version: 3,
        latest_approval_state: 'APPROVED',
        created_at: '2026-07-31T09:00:00.000Z',
      }],
      next_cursor: null,
      has_more: false,
    }),
    createModel: vi.fn().mockResolvedValue({
      model_id: modelId,
      model_name: '多任务模型',
      task_type: 'classification-segmentation',
      version_count: 0,
      latest_version: null,
      latest_approval_state: null,
      created_at: '2026-07-31T09:00:00.000Z',
    }),
    registerModelVersion: vi.fn().mockResolvedValue({
      model_version_id: modelVersionId,
      version: 1,
      approval_state: 'CANDIDATE',
      created_at: '2026-07-31T10:00:00.000Z',
    }),
    listModelVersions: vi.fn().mockResolvedValue({
      items: [{
        model_version_id: modelVersionId,
        model_id: modelId,
        version: 3,
        registry_name: 'tool-defect/multitask',
        registry_version: '3.0.0',
        approval_state: 'APPROVED',
        created_at: '2026-07-31T10:00:00.000Z',
      }],
      next_cursor: null,
      has_more: false,
    }),
    getModelDeployment: vi.fn().mockResolvedValue({
      deployment_id: '019f0000-0000-7000-8000-000000000004',
      model_version_id: modelVersionId,
      environment: 'SHADOW',
      strategy: 'PERCENTAGE',
      status: 'REQUESTED',
      record_version: 0,
      created_at: '2026-07-31T10:00:00.000Z',
    }),
    listModelDeployments: vi.fn().mockResolvedValue({
      items: [{
        deployment_id: '019f0000-0000-7000-8000-000000000004',
        model_version_id: modelVersionId,
        environment: 'SHADOW',
        strategy: 'PERCENTAGE',
        status: 'REQUESTED',
        created_at: '2026-07-31T10:00:00.000Z',
      }],
      next_cursor: null,
      has_more: false,
    }),
    createTrainingRun: vi.fn().mockResolvedValue({
      job_id: trainingRunId,
      status: 'QUEUED',
      poll_after_ms: 1000,
    }),
    approveModelDeployment: vi.fn().mockResolvedValue({
      accepted: true,
      request_id: '019f0000-0000-7000-8000-000000000005',
    }),
  } as unknown as ApiClient
}

describe('P6 MLOps 页面消费者', () => {
  it('R6 页面注册表移除数据集和训练入口', () => {
    expect(applicationRoutes.find((item) => item.name === 'datasets'))
      .toBeUndefined()
    expect(applicationRoutes.find((item) => item.name === 'training-runs'))
      .toBeUndefined()
  })

  it('R6 管理员可进入模型页面且旧数据集训练深链接不可达', () => {
    const featureNames = ['models', 'quality']
    const auditPermissions = new Set(['audit:read'])

    for (const name of featureNames) {
      const route = applicationRoutes.find((item) => item.name === name)
      expect(route, `${name} 路由必须存在`).toBeDefined()
      expect(
        hasRouteAccess(route?.meta, (permission) => auditPermissions.has(permission)),
        `${name} 应对后端允许的审计只读权限可见`,
      ).toBe(true)
      expect(
        hasRouteAccess(route?.meta, () => false),
        `${name} 不得对无权限用户可见`,
      ).toBe(false)
    }
  })

  it('生产员工没有模型、数据集或训练管理入口', () => {
    const permissions = new Set([
      'capture:read',
      'detection:read',
    ])

    for (const name of ['datasets', 'training-runs']) {
      const route = applicationRoutes.find((item) => item.name === name)
      expect(route).toBeUndefined()
    }
    expect(hasRouteAccess(
      applicationRoutes.find((item) => item.name === 'models')?.meta,
      (permission) => permissions.has(permission),
    )).toBe(false)
  })

  it('模型列表严格携带模型范围并消费冻结字段', async () => {
    const api = fakeApi()
    const page = await new ModelService(api).listModelVersions(modelId)
    expect(page.items[0]?.model_version_id).toBe(modelVersionId)
    expect(api.listModelVersions).toHaveBeenCalledWith({
      query: { model_id: modelId, page_size: 25 },
    })
  })

  it('数据集目录提供真实 ID，并可按状态发现冻结版本', async () => {
    const api = fakeApi()
    const service = new DatasetService(api)
    const catalog = await service.listDatasets({ pageSize: 200 })
    const versions = await service.listVersionCatalog({
      status: 'FROZEN',
      pageSize: 200,
    })

    expect(catalog.items[0]?.dataset_id).toBe(datasetId)
    expect(versions.items[0]?.version_id).toBe(datasetVersionId)
    expect(api.listDatasetVersionCatalog).toHaveBeenCalledWith({
      query: { page_size: 200, status: 'FROZEN' },
    })
  })

  it('数据集工作台可选择候选清单、创建构建任务并完成冻结审批', async () => {
    const api = fakeApi()
    const service = new DatasetService(api)
    const manifests = await service.listCandidateManifests(datasetId, {
      pageSize: 100,
    })
    const accepted = await service.createVersion({
      dataset_id: datasetId,
      candidate_manifest_id: manifests.items[0]!.candidate_manifest_id,
      purpose: '受控增量训练',
    })
    const candidateApproval = await service.approveCandidateManifest(
      candidateManifestId,
      { decision: 'APPROVE' },
    )
    const versionApproval = await service.approveVersion(
      datasetVersionId,
      { decision: 'APPROVE' },
    )

    expect(manifests.items[0]?.approval_state).toBe('APPROVED')
    expect(accepted.job_id).toBe(datasetVersionId)
    expect(candidateApproval.approval_state).toBe('APPROVED')
    expect(versionApproval.state).toBe('FROZEN')
    expect(api.listDatasetCandidateManifests).toHaveBeenCalledWith({
      query: { dataset_id: datasetId, page_size: 100 },
    })
    expect(api.createDatasetVersion).toHaveBeenCalledWith({
      body: {
        dataset_id: datasetId,
        candidate_manifest_id: candidateManifestId,
        purpose: '受控增量训练',
      },
    })
  })

  it('训练运行与部署记录都有目录入口，不要求手填查询 ID', async () => {
    const api = fakeApi()
    const runs = await new TrainingService(api).list({ status: 'QUEUED' })
    const deployments = await new DeploymentService(api).list({
      status: 'REQUESTED',
    })

    expect(runs.items[0]?.training_run_id).toBe(trainingRunId)
    expect(deployments.items[0]?.deployment_id)
      .toBe('019f0000-0000-7000-8000-000000000004')
    expect(api.listTrainingRuns).toHaveBeenCalledWith({
      query: { page_size: 50, status: 'QUEUED' },
    })
    expect(api.listModelDeployments).toHaveBeenCalledWith({
      query: { page_size: 50, status: 'REQUESTED' },
    })
  })

  it('模型目录可创建根资源，并支持跨模型查询已批准版本', async () => {
    const api = fakeApi()
    const service = new ModelService(api)
    const catalog = await service.listModels({ pageSize: 200 })
    const versions = await service.listModelVersions(undefined, {
      approvalState: 'APPROVED',
      pageSize: 100,
    })

    expect(catalog.items[0]?.model_id).toBe(modelId)
    expect(versions.items[0]?.model_version_id).toBe(modelVersionId)
    expect(api.listModelVersions).toHaveBeenLastCalledWith({
      query: { page_size: 100, approval_state: 'APPROVED' },
    })
  })

  it('模型登记只提交已绑定的完整供应链证据并进入候选状态', async () => {
    const api = fakeApi()
    const request = buildModelRegistrationRequest({
      modelId,
      trainingRunId,
      datasetVersionId,
      registryName: ' tool-defect-multitask ',
      registryVersion: ' 1 ',
      artifactBucket: ' td-models ',
      artifactObjectKey: ' models/multitask/1/package.tar.gz ',
      artifactSha256: 'a'.repeat(64),
      sbomSha256: 'b'.repeat(64),
      signatureKeyId: ' release-key-2026 ',
      inputSpec: '{"shape":[256,256,3],"dtype":"float32"}',
      outputSpec: '{"names":["cla_out","seg_out"]}',
      evaluationReportSha256: 'c'.repeat(64),
      thresholdGateSha256: 'd'.repeat(64),
    })

    const response = await new ModelService(api).registerModelVersion(request)

    expect(response.approval_state).toBe('CANDIDATE')
    expect(api.registerModelVersion).toHaveBeenCalledWith({
      body: {
        model_id: modelId,
        training_run_id: trainingRunId,
        dataset_version_id: datasetVersionId,
        registry_name: 'tool-defect-multitask',
        registry_version: '1',
        artifact_bucket: 'td-models',
        artifact_object_key: 'models/multitask/1/package.tar.gz',
        artifact_sha256: 'a'.repeat(64),
        sbom_sha256: 'b'.repeat(64),
        signature_key_id: 'release-key-2026',
        input_spec: { shape: [256, 256, 3], dtype: 'float32' },
        output_spec: { names: ['cla_out', 'seg_out'] },
        evaluation_summary: {
          evaluation_report_sha256: 'c'.repeat(64),
          threshold_gate_sha256: 'd'.repeat(64),
        },
      },
    })
  })

  it('模型登记对非法 JSON 和摘要安全失败', () => {
    const base = {
      modelId,
      trainingRunId,
      datasetVersionId,
      registryName: 'tool-defect-multitask',
      registryVersion: '1',
      artifactBucket: 'td-models',
      artifactObjectKey: 'models/multitask/1/package.tar.gz',
      artifactSha256: 'a'.repeat(64),
      sbomSha256: 'b'.repeat(64),
      signatureKeyId: 'release-key-2026',
      inputSpec: '{}',
      outputSpec: '{}',
      evaluationReportSha256: 'c'.repeat(64),
      thresholdGateSha256: 'd'.repeat(64),
    }

    expect(() => buildModelRegistrationRequest({
      ...base,
      inputSpec: '[]',
    })).toThrowError(ModelRegistrationInputError)
    expect(() => buildModelRegistrationRequest({
      ...base,
      artifactSha256: 'A'.repeat(64),
    })).toThrowError('模型包 SHA-256 必须是 64 位小写十六进制')
  })

  it('部署审批携带 If-Match 记录版本，不能静默覆盖', async () => {
    const api = fakeApi()
    const service = new DeploymentService(api)
    const deployment = await service.get('019f0000-0000-7000-8000-000000000004')
    await service.approve(deployment.deployment_id, deployment.record_version, {
      role: 'QUALITY_APPROVER',
      decision: 'APPROVE',
      reason: '影子观察前质量门槛已复核',
    })
    expect(api.approveModelDeployment).toHaveBeenCalledWith({
      path: { model_deployment_id: deployment.deployment_id },
      headers: { 'If-Match': '0' },
      body: {
        role: 'QUALITY_APPROVER',
        decision: 'APPROVE',
        reason: '影子观察前质量门槛已复核',
      },
    })
  })

  it('训练页面只创建排队任务，不把排队当成完成', async () => {
    const accepted = await new TrainingService(fakeApi()).create({
      dataset_version_id: modelVersionId,
      initial_model_version_id: null,
      training_config_version: '2026.07.31',
    })
    expect(accepted.status).toBe('QUEUED')
    expect(accepted.job_id).toBe(trainingRunId)
  })
})
