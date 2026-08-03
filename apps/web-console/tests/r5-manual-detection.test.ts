import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '@/api/client'
import type { DetectionBatchItem, JsonObject } from '@/api/generated'
import QuickReviewButtons from '@/features/manual-detection/QuickReviewButtons.vue'
import {
  detectImageType,
  ManualDetectionService,
  resultPriority,
  type PreparedImage,
} from '@/features/manual-detection/service'

const batch = {
  batch_id: '019f0000-0000-7000-8000-000000000001',
  batch_no: 'JC-20260803-00001',
  source: 'MANUAL_UPLOAD',
  created_by: '019f0000-0000-7000-8000-000000000002',
  usage_stage: 'UNSPECIFIED',
  status: 'PARTIALLY_COMPLETED',
  counts: { total: 10, completed: 10, defect_suspected: 2, normal: 6,
    inconclusive: 1, quality_rejected: 1, technical_failed: 0 },
  created_at: '2026-08-03T00:00:00Z', updated_at: '2026-08-03T00:01:00Z', version: 12,
} as const

function item(status: DetectionBatchItem['status'], outcome?: DetectionBatchItem['algorithm_outcome']): JsonObject {
  return {
    batch_item_id: crypto.randomUUID(), batch_id: batch.batch_id,
    image: { bucket: 'manual-originals', object_key: 'manual-originals/a.png',
      sha256: 'a'.repeat(64), size_bytes: 10, media_type: 'image/png' },
    status, ...(outcome === undefined ? {} : { algorithm_outcome: outcome }),
    created_at: '2026-08-03T00:00:00Z', updated_at: '2026-08-03T00:01:00Z',
  }
}

describe('R5 手工批量检测前端', () => {
  it('按实际文件头识别 PNG/JPEG 并拒绝伪装扩展名内容', () => {
    expect(detectImageType(new Uint8Array([137,80,78,71,13,10,26,10]))).toBe('image/png')
    expect(detectImageType(new Uint8Array([0xff,0xd8,0xff,0xe0]))).toBe('image/jpeg')
    expect(() => detectImageType(new Uint8Array([1,2,3]))).toThrow('TD-MANUAL-FILE-TYPE-001')
  })

  it('十图部分质量拒绝的计数完全读取后端且异常排序优先', async () => {
    const items = [item('COMPLETED','QUALIFIED'), item('QUALITY_REJECTED'),
      item('COMPLETED','INCONCLUSIVE'), item('COMPLETED','UNQUALIFIED')]
    const api = { async getDetectionBatchV2() { return { ...batch, items } } } as unknown as ApiClient
    const detail = await new ManualDetectionService(api).get(batch.batch_id)
    expect(detail.counts).toEqual(batch.counts)
    expect([...detail.items].sort((a,b) => resultPriority(a)-resultPriority(b)).map(resultPriority)).toEqual([0,1,2,3])
  })

  it('部分对象直传失败不抹掉同批其他上传结果', async () => {
    const calls: string[] = []
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input); calls.push(url)
      return new Response('', { status: url.endsWith('/bad') ? 503 : 200 })
    })
    const service = new ManualDetectionService({} as ApiClient, fetcher)
    const prepared = { file: new File(['x'], 'x.png'), mediaType: 'image/png', sha256: 'a'.repeat(64) } satisfies PreparedImage
    const base = { item: item('UPLOADING') as unknown as DetectionBatchItem, method: 'PUT' as const,
      headers: {}, expiresAt: '2026-08-03T00:10:00Z' }
    const settled = await Promise.allSettled([
      service.upload({ ...base, url: 'https://objects.invalid/good' }, prepared.file),
      service.upload({ ...base, url: 'https://objects.invalid/bad' }, prepared.file),
    ])
    expect(settled.map((result) => result.status)).toEqual(['fulfilled','rejected'])
    expect(calls).toHaveLength(2)
  })

  it('三按钮立即提交；失败重试复用幂等键且无法判断显示暂停提示', async () => {
    const submit = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined)
    const wrapper = mount(QuickReviewButtons, { props: { submit } })
    const unable = wrapper.findAll('button').find((button) => button.text() === '无法判断')
    expect(unable).toBeDefined()
    await unable?.trigger('click'); await vi.waitFor(() => expect(submit).toHaveBeenCalledTimes(1))
    await unable?.trigger('click'); await vi.waitFor(() => expect(submit).toHaveBeenCalledTimes(2))
    expect(submit.mock.calls[1]?.[1]).toBe(submit.mock.calls[0]?.[1])
    expect(wrapper.text()).toContain('保持暂停等待处理')
    expect(wrapper.text()).not.toContain('提交全部')
  })
})
