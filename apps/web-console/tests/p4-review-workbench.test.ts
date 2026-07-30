import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { ApiClient } from '@/api/client'
import type { ReviewTask, UploadTicketResponse } from '@/api/generated'
import { binaryMaskPng, rasterizeBinaryMask } from '@/components/image-workbench/binary-png'
import {
  MaskDraftStore,
  MaskHistory,
} from '@/components/image-workbench/mask-history'
import MaskWorkbench from '@/components/image-workbench/MaskWorkbench.vue'
import { projectLease } from '@/features/reviews/lease'
import { ReviewService } from '@/features/reviews/service'
import { applicationRoutes } from '@/router/routes'

const task: ReviewTask = {
  review_task_id: '019f0000-0000-7000-8000-000000000101',
  capture_id: '019f0000-0000-7000-8000-000000000102',
  status: 'CLAIMED',
  priority: 'P1',
  lease_expires_at: '2026-07-30T08:05:00.000Z',
  record_version: 4,
}

describe('P4 复核工作台', () => {
  it('笔迹可撤销、重做并只把稀疏坐标写入草稿', () => {
    window.localStorage.clear()
    const history = new MaskHistory()
    history.add({
      tool: 'brush',
      radius: 0.01,
      points: [{ x: 0.25, y: 0.5 }, { x: 0.3, y: 0.55 }],
    })
    history.undo()
    expect(history.strokes).toHaveLength(0)
    history.redo()
    expect(history.strokes).toHaveLength(1)

    const drafts = new MaskDraftStore(window.localStorage)
    drafts.save(task.review_task_id, history)
    const serialized = window.localStorage.getItem(
      `tool-defect.review-draft.${task.review_task_id}`,
    )
    expect(serialized).toContain('"strokes"')
    expect(serialized).not.toMatch(/https?:|signature|object_key|image_id/i)

    const restored = new MaskHistory()
    expect(drafts.load(task.review_task_id, restored)).toBe(true)
    expect(restored.strokes).toEqual(history.strokes)
  })

  it('导出的掩膜为原尺寸、灰度 PNG 且像素只有 0/255', async () => {
    const strokes = [
      {
        tool: 'brush' as const,
        radius: 0.1,
        points: [{ x: 0.5, y: 0.5 }],
      },
      {
        tool: 'eraser' as const,
        radius: 0.02,
        points: [{ x: 0.5, y: 0.5 }],
      },
    ]
    const pixels = rasterizeBinaryMask(32, 24, strokes)
    expect(new Set(pixels)).toEqual(new Set([0, 255]))
    expect(pixels[12 * 32 + 16]).toBe(0)

    const blob = await binaryMaskPng(32, 24, strokes)
    const bytes = new Uint8Array(await blob.arrayBuffer())
    expect([...bytes.slice(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10])
    expect(new DataView(bytes.buffer).getUint32(16)).toBe(32)
    expect(new DataView(bytes.buffer).getUint32(20)).toBe(24)
    expect(bytes[25]).toBe(0)
    expect(blob.type).toBe('image/png')
  })

  it('对象存储上传不会转发控制面回执', async () => {
    let sentHeaders = new Headers()
    const fetcher = async (_input: RequestInfo | URL, init?: RequestInit) => {
      sentHeaders = new Headers(init?.headers)
      return new Response(null, { status: 200 })
    }
    const service = new ReviewService({} as ApiClient, fetcher)
    const ticket: UploadTicketResponse = {
      image_id: '019f0000-0000-7000-8000-000000000103',
      upload: {
        method: 'PUT',
        url: 'https://objects.example.invalid/mask?temporary=one',
        expires_at: '2026-07-30T08:05:00.000Z',
        headers: {
          'Content-Type': 'image/png',
          'X-Tool-Defect-Upload-Receipt': 'opaque-control-receipt',
          'x-amz-checksum-sha256': 'checksum',
        },
      },
    }

    await expect(service.uploadMask(ticket, new Blob(['png']))).resolves.toBe(
      'opaque-control-receipt',
    )
    expect(sentHeaders.get('content-type')).toBe('image/png')
    expect(sentHeaders.get('x-amz-checksum-sha256')).toBe('checksum')
    expect(sentHeaders.has('x-tool-defect-upload-receipt')).toBe(false)
  })

  it('租约到期后明确阻断，路由仍由复核读取权限保护', () => {
    expect(
      projectLease(task, Date.parse('2026-07-30T08:04:01.000Z')).label,
    ).toBe('0:59')
    expect(
      projectLease(task, Date.parse('2026-07-30T08:05:00.000Z')),
    ).toMatchObject({ active: false, expired: true, label: '租约已到期' })

    const queue = applicationRoutes.find((route) => route.name === 'reviews')
    const workbench = applicationRoutes.find(
      (route) => route.name === 'review-workbench',
    )
    expect(queue?.path).toBe('/reviews')
    expect(workbench?.path).toBe('/reviews/:id')
    expect(queue?.meta?.permissions).toEqual(['review:read'])
    expect(workbench?.meta?.permissions).toEqual(['review:read'])
  })

  it('叠加默认关闭且工具不只依赖颜色表达', () => {
    window.localStorage.clear()
    const wrapper = mount(MaskWorkbench, {
      props: {
        reviewTaskId: task.review_task_id,
        sourceUrl: 'https://objects.example.invalid/original',
        overlayUrl: 'https://objects.example.invalid/overlay',
        width: 640,
        height: 480,
      },
    })
    const overlayToggle = wrapper.get('input[type="checkbox"]')
    expect((overlayToggle.element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.text()).toContain('画笔')
    expect(wrapper.text()).toContain('橡皮')
    expect(wrapper.text()).toContain('撤销')
    expect(wrapper.get('canvas').attributes('aria-label')).toBe('人工掩膜绘制区域')
  })
})
