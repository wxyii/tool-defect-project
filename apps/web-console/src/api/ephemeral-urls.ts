interface EphemeralUrl {
  readonly url: string
  readonly expiresAtEpochMs: number
}

/**
 * 签名地址仅保存在内存，过期后必须重新向后端申请。
 */
export class EphemeralUrlRegistry {
  private readonly entries = new Map<string, EphemeralUrl>()

  put(key: string, value: EphemeralUrl, nowEpochMs = Date.now()): void {
    const parsed = new URL(value.url)
    const localDevelopmentHost =
      parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1'
    const secureTransport =
      parsed.protocol === 'https:' ||
      (parsed.protocol === 'http:' && localDevelopmentHost)
    if (!secureTransport || parsed.username !== '' || parsed.password !== '') {
      throw new Error('TD-STORAGE-TICKET-INSECURE')
    }
    const lifetime = value.expiresAtEpochMs - nowEpochMs
    if (lifetime <= 0 || lifetime > 15 * 60_000) {
      throw new Error('TD-STORAGE-TICKET-TTL')
    }
    this.entries.set(key, Object.freeze({ ...value }))
  }

  get(key: string, nowEpochMs = Date.now()): string | null {
    const value = this.entries.get(key)
    if (value === undefined) {
      return null
    }
    if (value.expiresAtEpochMs <= nowEpochMs) {
      this.entries.delete(key)
      return null
    }
    return value.url
  }

  clear(): void {
    this.entries.clear()
  }
}
