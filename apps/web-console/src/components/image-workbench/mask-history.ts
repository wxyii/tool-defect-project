export type MaskTool = 'brush' | 'eraser'

export interface MaskPoint {
  readonly x: number
  readonly y: number
}

export interface MaskStroke {
  readonly tool: MaskTool
  readonly radius: number
  readonly points: readonly MaskPoint[]
}

export class MaskHistory {
  private committed: MaskStroke[] = []
  private reverted: MaskStroke[] = []

  get strokes(): readonly MaskStroke[] {
    return this.committed
  }

  get canUndo(): boolean {
    return this.committed.length > 0
  }

  get canRedo(): boolean {
    return this.reverted.length > 0
  }

  add(stroke: MaskStroke): void {
    const normalized = normalizeStroke(stroke)
    this.committed = [...this.committed, normalized]
    this.reverted = []
  }

  undo(): void {
    const stroke = this.committed.at(-1)
    if (stroke === undefined) return
    this.committed = this.committed.slice(0, -1)
    this.reverted = [...this.reverted, stroke]
  }

  redo(): void {
    const stroke = this.reverted.at(-1)
    if (stroke === undefined) return
    this.reverted = this.reverted.slice(0, -1)
    this.committed = [...this.committed, stroke]
  }

  clear(): void {
    this.committed = []
    this.reverted = []
  }

  serialize(): string {
    return JSON.stringify({ version: 1, strokes: this.committed })
  }

  restore(serialized: string): void {
    const parsed: unknown = JSON.parse(serialized)
    if (!isRecord(parsed) || parsed.version !== 1 || !Array.isArray(parsed.strokes)) {
      throw new Error('TD-MASK-DRAFT-001')
    }
    if (parsed.strokes.length > 500) throw new Error('TD-MASK-DRAFT-001')
    this.committed = parsed.strokes.map((stroke) => {
      if (!isRecord(stroke) || !Array.isArray(stroke.points)) {
        throw new Error('TD-MASK-DRAFT-001')
      }
      return normalizeStroke({
        tool: stroke.tool as MaskTool,
        radius: Number(stroke.radius),
        points: stroke.points.map((point) => {
          if (!isRecord(point)) throw new Error('TD-MASK-DRAFT-001')
          return { x: Number(point.x), y: Number(point.y) }
        }),
      })
    })
    this.reverted = []
  }
}

export class MaskDraftStore {
  constructor(private readonly storage: Storage) {}

  save(reviewTaskId: string, history: MaskHistory): void {
    this.storage.setItem(key(reviewTaskId), history.serialize())
  }

  load(reviewTaskId: string, history: MaskHistory): boolean {
    const value = this.storage.getItem(key(reviewTaskId))
    if (value === null) return false
    try {
      history.restore(value)
      return true
    } catch {
      this.clear(reviewTaskId)
      return false
    }
  }

  clear(reviewTaskId: string): void {
    this.storage.removeItem(key(reviewTaskId))
  }
}

function normalizeStroke(stroke: MaskStroke): MaskStroke {
  if (
    (stroke.tool !== 'brush' && stroke.tool !== 'eraser')
    || !Number.isFinite(stroke.radius)
    || stroke.radius < 0.001
    || stroke.radius > 0.1
    || stroke.points.length < 1
    || stroke.points.length > 20_000
  ) {
    throw new Error('TD-MASK-STROKE-001')
  }
  const points = stroke.points.map((point) => {
    if (
      !Number.isFinite(point.x)
      || !Number.isFinite(point.y)
      || point.x < 0
      || point.x > 1
      || point.y < 0
      || point.y > 1
    ) {
      throw new Error('TD-MASK-STROKE-001')
    }
    return Object.freeze({ x: point.x, y: point.y })
  })
  return Object.freeze({
    tool: stroke.tool,
    radius: stroke.radius,
    points: Object.freeze(points),
  })
}

function key(reviewTaskId: string): string {
  return `tool-defect.review-draft.${reviewTaskId}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
