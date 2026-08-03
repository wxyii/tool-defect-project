import { describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '@/api/client'
import { DeploymentService } from '@/features/models/deployment-service'
import { ModelService } from '@/features/models/service'
import { hasRouteAccess } from '@/router/access'
import { applicationRoutes } from '@/router/routes'

const modelVersionId = '019f0000-0000-7000-8000-000000000001'
const modelId = '019f0000-0000-7000-8000-000000000002'

function fakeApi(): ApiClient {
  return {
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

  it('部署记录有目录入口，不要求手填查询 ID', async () => {
    const api = fakeApi()
    const deployments = await new DeploymentService(api).list({
      status: 'REQUESTED',
    })

    expect(deployments.items[0]?.deployment_id)
      .toBe('019f0000-0000-7000-8000-000000000004')
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

})
