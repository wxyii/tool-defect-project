import type { AuthSession, TokenRefreshProvider } from './types'
import {
  HttpOidcTransport,
  OidcAuthorizationCoordinator,
  type OidcClientConfiguration,
  OidcSessionProvider,
  SessionStorageAuthorizationTransactionStore,
} from './oidc'

export interface OidcRuntime {
  readonly configured: boolean
  readonly refreshProvider: TokenRefreshProvider
  createAuthorizationRequest(redirectAfterLogin: string): Promise<string>
  completeAuthorizationCallback(callbackUrl: string): Promise<{
    readonly session: AuthSession
    readonly redirectAfterLogin: string
  }>
  revokeSession(refreshToken: string | undefined): Promise<void>
}

let currentRuntime: OidcRuntime = unavailableRuntime()

export function configureOidcRuntime(runtime: OidcRuntime): void {
  currentRuntime = runtime
}

export function useOidcRuntime(): OidcRuntime {
  return currentRuntime
}

export function createOidcRuntimeFromEnvironment(
  environment: ImportMetaEnv,
  browser: Pick<Window, 'location' | 'sessionStorage'>,
  fetcher: typeof fetch = fetch,
): OidcRuntime {
  let configuration: OidcClientConfiguration | null
  try {
    configuration = readConfiguration(environment, browser.location.origin)
  } catch (error) {
    return unavailableRuntime(
      error instanceof Error && error.message.startsWith('TD-AUTH-')
        ? error.message
        : 'TD-AUTH-CONFIG-001',
    )
  }
  if (configuration === null) {
    return unavailableRuntime()
  }
  const transport = new HttpOidcTransport(configuration, { fetcher })
  const provider = new OidcSessionProvider(transport)
  const coordinator = new OidcAuthorizationCoordinator(
    configuration,
    provider,
    new SessionStorageAuthorizationTransactionStore(browser.sessionStorage),
  )
  return {
    configured: true,
    refreshProvider: provider,
    createAuthorizationRequest: (redirectAfterLogin) =>
      coordinator.createAuthorizationRequest(redirectAfterLogin),
    completeAuthorizationCallback: (callbackUrl) =>
      coordinator.completeAuthorizationCallback(callbackUrl),
    revokeSession: (refreshToken) => provider.revoke(refreshToken),
  }
}

function readConfiguration(
  environment: ImportMetaEnv,
  origin: string,
): OidcClientConfiguration | null {
  const authorizationEndpoint = nonEmpty(
    environment.VITE_OIDC_AUTHORIZATION_ENDPOINT,
  )
  const tokenEndpoint = nonEmpty(environment.VITE_OIDC_TOKEN_ENDPOINT)
  const userInfoEndpoint = nonEmpty(environment.VITE_OIDC_USERINFO_ENDPOINT)
  const clientId = nonEmpty(environment.VITE_OIDC_CLIENT_ID)
  if (
    authorizationEndpoint === null ||
    tokenEndpoint === null ||
    userInfoEndpoint === null ||
    clientId === null
  ) {
    return null
  }
  const secureOrigin = browserOrigin(origin)
  const redirectUri =
    nonEmpty(environment.VITE_OIDC_REDIRECT_URI) ??
    `${secureOrigin}/auth/callback`
  const scopes = (
    nonEmpty(environment.VITE_OIDC_SCOPES) ?? 'openid profile offline_access'
  )
    .split(/\s+/)
    .filter(Boolean)
  if (!scopes.includes('openid')) {
    throw new Error('TD-AUTH-CONFIG-SCOPE-001')
  }
  const revocationEndpoint = nonEmpty(
    environment.VITE_OIDC_REVOCATION_ENDPOINT,
  )
  return {
    authorizationEndpoint: secureEndpoint(authorizationEndpoint),
    tokenEndpoint: secureEndpoint(tokenEndpoint),
    userInfoEndpoint: secureEndpoint(userInfoEndpoint),
    ...(revocationEndpoint === null
      ? {}
      : { revocationEndpoint: secureEndpoint(revocationEndpoint) }),
    clientId,
    redirectUri: sameOriginRedirect(redirectUri, secureOrigin),
    scopes,
  }
}

function unavailableRuntime(errorCode = 'TD-AUTH-CONFIG-001'): OidcRuntime {
  const reject = (): Promise<never> =>
    Promise.reject(new Error(errorCode))
  return {
    configured: false,
    refreshProvider: { refresh: reject },
    createAuthorizationRequest: reject,
    completeAuthorizationCallback: reject,
    revokeSession: reject,
  }
}

function secureEndpoint(value: string): string {
  const url = new URL(value)
  const local = url.hostname === 'localhost' || url.hostname === '127.0.0.1'
  if (
    (url.protocol !== 'https:' && !(url.protocol === 'http:' && local)) ||
    url.username.length > 0 ||
    url.password.length > 0 ||
    url.hash.length > 0
  ) {
    throw new Error('TD-AUTH-CONFIG-HTTPS-001')
  }
  return url.toString()
}

function sameOriginRedirect(value: string, origin: string): string {
  const url = new URL(value, origin)
  if (url.origin !== origin) {
    throw new Error('TD-AUTH-CONFIG-REDIRECT-001')
  }
  return url.toString()
}

function browserOrigin(value: string): string {
  const url = new URL(value)
  const local = url.hostname === 'localhost' || url.hostname === '127.0.0.1'
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && local)) {
    throw new Error('TD-AUTH-CONFIG-ORIGIN-001')
  }
  return url.origin
}

function nonEmpty(value: string | undefined): string | null {
  const normalized = value?.trim()
  return normalized === undefined || normalized.length === 0 ? null : normalized
}
