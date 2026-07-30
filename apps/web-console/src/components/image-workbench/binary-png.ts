import type { MaskStroke } from './mask-history'

const PNG_SIGNATURE = Uint8Array.of(137, 80, 78, 71, 13, 10, 26, 10)

export async function binaryMaskPng(
  width: number,
  height: number,
  strokes: readonly MaskStroke[],
): Promise<Blob> {
  const pixels = rasterizeBinaryMask(width, height, strokes)
  const scanlines = new Uint8Array(height * (width + 1))
  for (let y = 0; y < height; y += 1) {
    const target = y * (width + 1)
    scanlines[target] = 0
    scanlines.set(pixels.subarray(y * width, (y + 1) * width), target + 1)
  }
  const compressed = new Uint8Array(
    await new Response(
      new Blob([scanlines]).stream().pipeThrough(new CompressionStream('deflate')),
    ).arrayBuffer(),
  )
  const header = new Uint8Array(13)
  const view = new DataView(header.buffer)
  view.setUint32(0, width)
  view.setUint32(4, height)
  header[8] = 8
  header[9] = 0
  return new Blob([
    arrayBuffer(PNG_SIGNATURE),
    arrayBuffer(pngChunk('IHDR', header)),
    arrayBuffer(pngChunk('IDAT', compressed)),
    arrayBuffer(pngChunk('IEND', new Uint8Array())),
  ], { type: 'image/png' })
}

export function rasterizeBinaryMask(
  width: number,
  height: number,
  strokes: readonly MaskStroke[],
): Uint8Array {
  if (
    !Number.isInteger(width)
    || !Number.isInteger(height)
    || width < 1
    || height < 1
    || width * height > 100_000_000
  ) {
    throw new Error('TD-MASK-DIMENSIONS-001')
  }
  const pixels = new Uint8Array(width * height)
  for (const stroke of strokes) {
    const radius = Math.max(1, Math.round(stroke.radius * Math.min(width, height)))
    const value = stroke.tool === 'brush' ? 255 : 0
    for (let index = 0; index < stroke.points.length; index += 1) {
      const current = stroke.points[index]
      if (current === undefined) continue
      const previous = stroke.points[Math.max(0, index - 1)] ?? current
      const x0 = previous.x * (width - 1)
      const y0 = previous.y * (height - 1)
      const x1 = current.x * (width - 1)
      const y1 = current.y * (height - 1)
      const distance = Math.hypot(x1 - x0, y1 - y0)
      const steps = Math.max(1, Math.ceil(distance / Math.max(1, radius * 0.35)))
      for (let step = 0; step <= steps; step += 1) {
        const ratio = step / steps
        stamp(
          pixels,
          width,
          height,
          Math.round(x0 + (x1 - x0) * ratio),
          Math.round(y0 + (y1 - y0) * ratio),
          radius,
          value,
        )
      }
    }
  }
  return pixels
}

function stamp(
  pixels: Uint8Array,
  width: number,
  height: number,
  centerX: number,
  centerY: number,
  radius: number,
  value: number,
): void {
  const minX = Math.max(0, centerX - radius)
  const maxX = Math.min(width - 1, centerX + radius)
  const minY = Math.max(0, centerY - radius)
  const maxY = Math.min(height - 1, centerY + radius)
  const squared = radius * radius
  for (let y = minY; y <= maxY; y += 1) {
    for (let x = minX; x <= maxX; x += 1) {
      if ((x - centerX) ** 2 + (y - centerY) ** 2 <= squared) {
        pixels[y * width + x] = value
      }
    }
  }
}

function pngChunk(type: string, data: Uint8Array): Uint8Array {
  const typeBytes = new TextEncoder().encode(type)
  const result = new Uint8Array(12 + data.length)
  const view = new DataView(result.buffer)
  view.setUint32(0, data.length)
  result.set(typeBytes, 4)
  result.set(data, 8)
  view.setUint32(8 + data.length, crc32(result.subarray(4, 8 + data.length)))
  return result
}

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff
  for (const byte of data) {
    crc ^= byte
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1))
    }
  }
  return (crc ^ 0xffffffff) >>> 0
}

function arrayBuffer(data: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(data.length)
  copy.set(data)
  return copy.buffer
}
