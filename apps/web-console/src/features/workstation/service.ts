import type { DetectionService } from '@/features/detections/service'
import {
  WorkstationProjection,
  type WorkstationSnapshot,
} from './projection'

export class WorkstationService {
  constructor(
    private readonly detections: DetectionService,
    private readonly projection = new WorkstationProjection(),
    private readonly now = () => new Date().toISOString(),
  ) {}

  get snapshot(): WorkstationSnapshot {
    return this.projection.snapshot
  }

  async refresh(): Promise<WorkstationSnapshot> {
    try {
      const page = await this.detections.list({ pageSize: 6 })
      const first = page.items[0]
      const current =
        first === undefined
          ? null
          : await this.detections.get(first.detection_task_id)
      return this.projection.applyOnline(current, page.items, this.now())
    } catch (error) {
      this.projection.markOffline()
      throw error
    }
  }
}
