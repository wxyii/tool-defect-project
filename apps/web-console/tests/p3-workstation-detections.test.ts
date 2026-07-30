import { describe, expect, it } from 'vitest'

import type {
  DetectionDetail,
  DetectionSummary,
} from '@/api/generated'
import { ImageTicketLoader } from '@/features/detections/image-tickets'
import type { DetectionService } from '@/features/detections/service'
import { WorkstationProjection } from '@/features/workstation/projection'

const summary: DetectionSummary = {
  detection_task_id: '019f0000-0000-7000-8000-000000000002',
  task_status: 'RUNNING',
  algorithm_outcome: null,
  confidence: null,
  model_version: 'model/1',
}

function detail(status: DetectionDetail['capture']['capture_status']): DetectionDetail {
  return {
    capture: {
      capture_id: '019f0000-0000-7000-8000-000000000001',
      capture_status: status,
      business_disposition: status === 'FINALIZED' ? 'PASS' : null,
      poll_after_ms: 1000,
    },
    detection: summary,
    attempts: [],
    disposition_history: [],
    images: [],
    versions: {},
  }
}

describe('P3 工位投影和图片授权', () => {
  it('断线及较旧刷新都不能让同一采集状态倒退', () => {
    const projection = new WorkstationProjection()
    projection.applyOnline(detail('FINALIZED'), [summary], '2026-07-30T00:00:00Z')

    const stale = projection.applyOnline(
      detail('PROCESSING'),
      [summary],
      '2026-07-30T00:00:01Z',
    )
    const offline = projection.markOffline()

    expect(stale.current?.capture.capture_status).toBe('FINALIZED')
    expect(stale.current?.capture.business_disposition).toBe('PASS')
    expect(offline.connection).toBe('OFFLINE')
    expect(offline.current?.capture.capture_status).toBe('FINALIZED')
  })

  it('签名地址过期后重新申请且不使用长期缓存', async () => {
    let calls = 0
    let now = Date.parse('2026-07-30T00:00:00.000Z')
    const detections = {
      async imageTicket() {
        calls += 1
        return {
          method: 'GET' as const,
          url: `https://objects.example.invalid/view-${calls}`,
          expires_at: new Date(now + 60_000).toISOString(),
        }
      },
    } as unknown as DetectionService
    const loader = new ImageTicketLoader(detections, undefined, () => now)

    const first = await loader.get('019f0000-0000-7000-8000-000000000004')
    const cached = await loader.get('019f0000-0000-7000-8000-000000000004')
    now += 60_001
    const refreshed = await loader.get(
      '019f0000-0000-7000-8000-000000000004',
    )

    expect(first).toBe(cached)
    expect(refreshed).not.toBe(first)
    expect(calls).toBe(2)
  })
})
