import { describe, expect, it } from 'vitest'

import { apiErrorMessage, toApiError } from '@/api/errors'

describe('统一接口错误解析', () => {
  it('读取第二版 error_code 字段', async () => {
    const error = await toApiError(new Response(JSON.stringify({
      error_code: 'TD-MANUAL-DETECTION-CONFLICT',
      message: '批次版本冲突',
      request_id: 'request-v2',
      retryable: true,
      details: [],
    }), {
      status: 409,
      headers: { 'Content-Type': 'application/json' },
    }))

    expect(error.code).toBe('TD-MANUAL-DETECTION-CONFLICT')
    expect(error.message).toBe('批次版本冲突')
    expect(error.requestId).toBe('request-v2')
    expect(error.retryable).toBe(true)
    expect(apiErrorMessage(error, '回退消息')).toBe(
      '批次版本冲突（TD-MANUAL-DETECTION-CONFLICT，请求标识 request-v2）',
    )
  })

  it('继续兼容第一版 code 字段', async () => {
    const error = await toApiError(new Response(JSON.stringify({
      code: 'TD-LEGACY-FORBIDDEN',
      message: '无权执行此操作',
      request_id: 'request-v1',
    }), {
      status: 403,
      headers: { 'Content-Type': 'application/json' },
    }))

    expect(error.code).toBe('TD-LEGACY-FORBIDDEN')
    expect(error.status).toBe(403)
  })

  it('非接口错误继续使用页面安全回退消息', () => {
    expect(apiErrorMessage(new Error('底层异常'), '操作失败')).toBe('操作失败')
  })
})
