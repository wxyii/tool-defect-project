import type { ReviewTask } from '@/api/generated'

export interface LeaseProjection {
  readonly active: boolean
  readonly expired: boolean
  readonly remainingSeconds: number
  readonly label: string
}

export function projectLease(
  task: ReviewTask,
  nowEpochMs = Date.now(),
): LeaseProjection {
  if (task.status !== 'CLAIMED' || task.lease_expires_at == null) {
    return Object.freeze({
      active: false,
      expired: false,
      remainingSeconds: 0,
      label: '未占用',
    })
  }
  const expiresAt = Date.parse(task.lease_expires_at)
  if (!Number.isFinite(expiresAt)) {
    return Object.freeze({
      active: false,
      expired: true,
      remainingSeconds: 0,
      label: '租约时间无效',
    })
  }
  const remainingSeconds = Math.max(0, Math.ceil((expiresAt - nowEpochMs) / 1000))
  if (remainingSeconds === 0) {
    return Object.freeze({
      active: false,
      expired: true,
      remainingSeconds,
      label: '租约已到期',
    })
  }
  const minutes = Math.floor(remainingSeconds / 60)
  const seconds = String(remainingSeconds % 60).padStart(2, '0')
  return Object.freeze({
    active: true,
    expired: false,
    remainingSeconds,
    label: `${minutes}:${seconds}`,
  })
}
