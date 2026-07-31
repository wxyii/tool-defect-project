import { describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '@/api/client'
import { DeploymentService } from '@/features/models/deployment-service'
import { ModelService } from '@/features/models/service'
import { TrainingService } from '@/features/training/service'

const modelVersionId = '019f0000-0000-7000-8000-000000000001'
const modelId = '019f0000-0000-7000-8000-000000000002'
const trainingRunId = '019f0000-0000-7000-8000-000000000003'

function fakeApi(): ApiClient {
  return {
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
  it('模型列表严格携带模型范围并消费冻结字段', async () => {
    const api = fakeApi()
    const page = await new ModelService(api).listModelVersions(modelId)
    expect(page.items[0]?.model_version_id).toBe(modelVersionId)
    expect(api.listModelVersions).toHaveBeenCalledWith({
      query: { model_id: modelId, page_size: 25 },
    })
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
