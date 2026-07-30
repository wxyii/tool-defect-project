export interface FieldError {
  readonly field: string
  readonly reason: string
}

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly requestId: string | null,
    readonly traceId: string | null,
    readonly retryable: boolean,
    readonly details: readonly FieldError[],
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function toApiError(response: Response): Promise<ApiError> {
  let raw: unknown
  try {
    raw = await response.json()
  } catch {
    raw = null
  }
  const payload = isRecord(raw) ? raw : {}
  return new ApiError(
    stringField(payload, 'code') ?? `TD-HTTP-${response.status}`,
    stringField(payload, 'message') ?? '请求失败，请稍后重试',
    stringField(payload, 'request_id'),
    stringField(payload, 'trace_id'),
    payload.retryable === true,
    parseDetails(payload.details),
    response.status,
  )
}

function parseDetails(value: unknown): readonly FieldError[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.flatMap((entry) => {
    if (!isRecord(entry)) {
      return []
    }
    const field = stringField(entry, 'field')
    const reason = stringField(entry, 'reason')
    return field !== null && reason !== null ? [{ field, reason }] : []
  })
}

function stringField(
  value: Record<string, unknown>,
  key: string,
): string | null {
  return typeof value[key] === 'string' ? value[key] : null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
