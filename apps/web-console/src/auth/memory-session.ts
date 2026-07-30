import type { AuthSession, AuthTokens, TokenRefreshProvider } from './types'

export class StaleSessionError extends Error {
  constructor() {
    super('TD-AUTH-SESSION-STALE-001')
    this.name = 'StaleSessionError'
  }
}

/**
 * 唯一令牌容器。实例仅存于 JavaScript 内存，不实现任何持久化接口。
 */
export class MemorySession {
  private current: AuthSession | null = null
  private refreshInFlight: Promise<AuthTokens> | null = null
  private generation = 0
  private readonly generationListeners = new Set<() => void>()

  get session(): AuthSession | null {
    return this.current
  }

  get accessToken(): string | null {
    return this.current?.tokens.accessToken ?? null
  }

  set(session: AuthSession): void {
    this.current = freezeSession(session)
    this.refreshInFlight = null
    this.advanceGeneration()
  }

  clear(): void {
    this.current = null
    this.refreshInFlight = null
    this.advanceGeneration()
  }

  captureGeneration(): number {
    return this.generation
  }

  assertGeneration(expected: number): void {
    if (this.generation !== expected) {
      throw new StaleSessionError()
    }
  }

  onGenerationChange(listener: () => void): () => void {
    this.generationListeners.add(listener)
    return () => {
      this.generationListeners.delete(listener)
    }
  }

  isExpired(nowEpochMs = Date.now(), skewMs = 30_000): boolean {
    const tokens = this.current?.tokens
    return tokens === undefined || tokens.expiresAtEpochMs <= nowEpochMs + skewMs
  }

  async refresh(provider: TokenRefreshProvider): Promise<AuthTokens> {
    if (this.current === null) {
      throw new Error('TD-AUTH-SESSION-001')
    }
    if (this.refreshInFlight !== null) {
      return this.refreshInFlight
    }
    const session = this.current
    const generation = this.generation
    const assertCurrentSession = (): void => {
      if (this.generation !== generation || this.current !== session) {
        throw new StaleSessionError()
      }
    }
    this.refreshInFlight = provider
      .refresh(session.tokens.refreshToken)
      .then(
        (tokens) => {
          assertCurrentSession()
          this.current = freezeSession({
            identity: session.identity,
            tokens,
          })
          return this.current.tokens
        },
        (error: unknown) => {
          assertCurrentSession()
          throw error
        }
      )
      .finally(() => {
        if (this.generation === generation) {
          this.refreshInFlight = null
        }
      })
    return this.refreshInFlight
  }

  private advanceGeneration(): void {
    this.generation += 1
    for (const listener of [...this.generationListeners]) {
      try {
        listener()
      } catch {
        // 会话状态已更新；观察者异常不得回滚安全失效。
      }
    }
  }
}

function freezeSession(session: AuthSession): AuthSession {
  const identity = Object.freeze({
    ...session.identity,
    roles: Object.freeze([...session.identity.roles]),
    permissions: Object.freeze([...session.identity.permissions]),
  })
  const tokens = Object.freeze({ ...session.tokens })
  return Object.freeze({ identity, tokens })
}
