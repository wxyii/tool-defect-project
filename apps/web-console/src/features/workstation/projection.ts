import type {
  CaptureStatus,
  DetectionDetail,
  DetectionSummary,
} from '@/api/generated'

const CAPTURE_RANK: Record<CaptureStatus, number> = {
  CREATED: 0,
  UPLOADING: 1,
  READY: 2,
  SUBMITTED: 3,
  PROCESSING: 4,
  REVIEW_PENDING: 5,
  FINALIZED: 6,
  FAILED: 6,
}

export interface WorkstationSnapshot {
  readonly connection: 'ONLINE' | 'OFFLINE'
  readonly current: DetectionDetail | null
  readonly recent: readonly DetectionSummary[]
  readonly lastSynchronizedAt: string | null
  readonly edge: Readonly<{
    readonly queueDepth: number | null
    readonly oldestTaskAgeSeconds: number | null
    readonly diskUsageRatio: number | null
  }>
}

export class WorkstationProjection {
  private value: WorkstationSnapshot = Object.freeze({
    connection: 'OFFLINE',
    current: null,
    recent: Object.freeze([]),
    lastSynchronizedAt: null,
    edge: Object.freeze({
      queueDepth: null,
      oldestTaskAgeSeconds: null,
      diskUsageRatio: null,
    }),
  })

  get snapshot(): WorkstationSnapshot {
    return this.value
  }

  applyOnline(
    current: DetectionDetail | null,
    recent: readonly DetectionSummary[],
    synchronizedAt: string,
  ): WorkstationSnapshot {
    const previous = this.value.current
    const acceptedCurrent =
      previous !== null
      && current !== null
      && previous.capture.capture_id === current.capture.capture_id
      && CAPTURE_RANK[current.capture.capture_status]
        < CAPTURE_RANK[previous.capture.capture_status]
        ? previous
        : current
    this.value = Object.freeze({
      connection: 'ONLINE',
      current: acceptedCurrent,
      recent: Object.freeze([...recent]),
      lastSynchronizedAt: synchronizedAt,
      edge: this.value.edge,
    })
    return this.value
  }

  markOffline(): WorkstationSnapshot {
    this.value = Object.freeze({
      ...this.value,
      connection: 'OFFLINE',
    })
    return this.value
  }
}
