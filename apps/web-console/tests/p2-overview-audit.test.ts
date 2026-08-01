import { describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '@/api/client'
import type { JsonObject } from '@/api/generated'
import { AuditService, parseAuditRecordPage } from '@/features/audit/service'
import { OverviewService, parseSystemOverview } from '@/features/overview/service'
import { hasRouteAccess } from '@/router/access'
import { applicationRoutes } from '@/router/routes'

const overviewResponse = {
  generated_at: '2026-08-01T05:00:00Z',
  window: {
    timezone: 'Asia/Shanghai',
    current_start: '2026-07-31T16:00:00Z',
    current_end: '2026-08-01T05:00:00Z',
    previous_start: '2026-07-30T16:00:00Z',
    previous_end: '2026-07-31T05:00:00Z',
  },
  captures: { total: 20, pass: 12, fail: 3, hold: 2, unresolved: 3 },
  reviews: {
    total: 4,
    pending: 1,
    claimed: 1,
    second_review_pending: 1,
    escalated: 1,
    oldest_age_seconds: 7200,
  },
  fleet: {
    stations_total: 3,
    stations_online: 2,
    stations_maintenance: 1,
    devices_total: 8,
    devices_online: 5,
    devices_degraded: 1,
    devices_offline: 2,
    heartbeat_freshness_seconds: 120,
  },
  inference: {
    queued: 2,
    running: 1,
    retry_wait: 1,
    dead: 1,
    failures_24h: 1,
    completed_in_window: 15,
    p95_duration_ms: 920.5,
  },
  model_runtime: {
    production: {
      deployment_id: '019f0000-0000-7000-8000-000000000001',
      model_version_id: '019f0000-0000-7000-8000-000000000002',
      registry_name: 'tool-defect/multitask',
      registry_version: '3.0.0',
      traffic_ratio: 1,
      effective_at: '2026-07-31T08:00:00Z',
    },
    active_shadow_deployments: 1,
    active_canary_deployments: 1,
    canary_traffic_ratio: 0.1,
  },
  outcome_comparison: {
    current: { qualified: 11, unqualified: 3, inconclusive: 1 },
    previous: { qualified: 9, unqualified: 4, inconclusive: 2 },
  },
  quality_comparison: {
    current: { ok: 17, warning: 2, rejected: 1 },
    previous: { ok: 15, warning: 3, rejected: 2 },
  },
} satisfies JsonObject

const auditResponse = {
  items: [{
    audit_id: '019f0000-0000-7000-8000-000000000003',
    occurred_at: '2026-08-01T04:58:00Z',
    actor_type: 'USER',
    actor_id: '019f0000-0000-7000-8000-000000000004',
    actor_ip: '127.0.0.1',
    action: 'audit.records.query',
    resource_type: 'audit_log',
    resource_id: '2026-08-01T00:00:00Z/2026-08-01T05:00:00Z',
    before_digest: null,
    after_digest: 'a'.repeat(64),
    reason: '只读审计查询',
    request_id: 'request-1',
    trace_id: 'b'.repeat(32),
    result: 'SUCCESS',
    error_code: null,
  }],
  next_cursor: 'next-page',
  has_more: true,
} satisfies JsonObject

function fakeApi(): ApiClient {
  return {
    getSystemOverview: vi.fn().mockResolvedValue(overviewResponse),
    listAuditRecords: vi.fn().mockResolvedValue(auditResponse),
  } as unknown as ApiClient
}

describe('系统总览与审计页面消费者', () => {
  it('两个入口使用真实页面并保持各自权限边界', () => {
    const dashboard = applicationRoutes.find((route) => route.name === 'dashboard')
    const audit = applicationRoutes.find((route) => route.name === 'audit')
    const placeholder = applicationRoutes.find((route) => route.name === 'devices')

    expect(dashboard?.component).not.toBe(placeholder?.component)
    expect(audit?.component).not.toBe(placeholder?.component)
    expect(dashboard?.props).toBeUndefined()
    expect(audit?.props).toBeUndefined()
    expect(hasRouteAccess(dashboard?.meta, (permission) => permission === 'detection:read')).toBe(true)
    expect(hasRouteAccess(audit?.meta, (permission) => permission === 'audit:read')).toBe(true)
    expect(hasRouteAccess(audit?.meta, () => false)).toBe(false)
  })

  it('总览服务消费冻结响应并拒绝额外字段', async () => {
    const api = fakeApi()
    const response = await new OverviewService(api).get()

    expect(response.captures.total).toBe(20)
    expect(response.model_runtime.production?.registry_version).toBe('3.0.0')
    expect(api.getSystemOverview).toHaveBeenCalledOnce()
    expect(() => parseSystemOverview({
      ...overviewResponse,
      unexpected: true,
    })).toThrowError('TD-CONTRACT-INCOMPATIBLE-001')
  })

  it('审计服务传递 UTC 时间窗和筛选条件并验证证据字段', async () => {
    const api = fakeApi()
    const response = await new AuditService(api).list({
      pageSize: 50,
      startTime: '2026-08-01T00:00:00Z',
      endTime: '2026-08-01T05:00:00Z',
      actorId: 'operator',
      action: 'review',
      result: 'SUCCESS',
    })

    expect(response.items[0]?.action).toBe('audit.records.query')
    expect(api.listAuditRecords).toHaveBeenCalledWith({
      query: {
        page_size: 50,
        start_time: '2026-08-01T00:00:00Z',
        end_time: '2026-08-01T05:00:00Z',
        actor_id: 'operator',
        action: 'review',
        result: 'SUCCESS',
      },
    })
    expect(() => parseAuditRecordPage({
      ...auditResponse,
      items: [{ ...auditResponse.items[0], trace_id: 'not-a-trace' }],
    })).toThrowError('TD-CONTRACT-INCOMPATIBLE-001')
  })
})
