import { EphemeralUrlRegistry } from '@/api/ephemeral-urls'
import type { DetectionService } from './service'

export class ImageTicketLoader {
  constructor(
    private readonly detections: DetectionService,
    private readonly registry = new EphemeralUrlRegistry(),
    private readonly now = () => Date.now(),
  ) {}

  async get(imageId: string, forceRefresh = false): Promise<string> {
    const cached = forceRefresh ? null : this.registry.get(imageId, this.now())
    if (cached !== null) return cached
    const ticket = await this.detections.imageTicket(imageId)
    const expiresAt = Date.parse(ticket.expires_at)
    if (!Number.isFinite(expiresAt)) {
      throw new Error('TD-STORAGE-TICKET-EXPIRY-001')
    }
    this.registry.put(
      imageId,
      { url: ticket.url, expiresAtEpochMs: expiresAt },
      this.now(),
    )
    const url = this.registry.get(imageId, this.now())
    if (url === null) throw new Error('TD-STORAGE-TICKET-EXPIRY-001')
    return url
  }

  clear(): void {
    this.registry.clear()
  }
}
