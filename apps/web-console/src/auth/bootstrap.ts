import type { AuthSession } from './types'
import type { OidcRuntime } from './runtime'
import { StaleSessionError } from './memory-session'
import { memorySession } from '@/stores/auth'

export interface SessionEstablisher {
  establish(session: AuthSession): void
  clear(): void
}

export async function bootstrapOidcCallback(
  runtime: OidcRuntime,
  auth: SessionEstablisher,
  callbackUrl: string,
  signal?: AbortSignal,
): Promise<string> {
  const sessionGeneration = memorySession.captureGeneration()
  try {
    const result = await runtime.completeAuthorizationCallback(callbackUrl)
    if (signal?.aborted) {
      throw new StaleSessionError()
    }
    memorySession.assertGeneration(sessionGeneration)
    auth.establish(result.session)
    return result.redirectAfterLogin
  } catch (error) {
    if (!(error instanceof StaleSessionError)) {
      auth.clear()
    }
    throw error
  }
}
