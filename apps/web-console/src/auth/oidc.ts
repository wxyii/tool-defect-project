import type { AuthIdentity, AuthSession, AuthTokens, TokenRefreshProvider } from './types'

export interface OidcClientConfiguration {
  readonly authorizationEndpoint: string
  readonly tokenEndpoint: string
  readonly userInfoEndpoint: string
  readonly revocationEndpoint?: string
  readonly clientId: string
  readonly redirectUri: string
  readonly scopes: readonly string[]
}

export interface OidcTransport {
  exchangeAuthorizationCode(
    code: string,
    codeVerifier: string,
  ): Promise<AuthSession>

  refresh(refreshToken: string | undefined): Promise<AuthTokens>

  revoke(refreshToken: string | undefined): Promise<void>
}

export interface AuthorizationTransaction {
  readonly state: string
  readonly codeVerifier: string
  readonly redirectAfterLogin: string
}

export interface AuthorizationTransactionStore {
  save(transaction: AuthorizationTransaction): void
  take(): AuthorizationTransaction | null
}

export interface AuthorizationCallbackResult {
  readonly session: AuthSession
  readonly redirectAfterLogin: string
}

const TRANSACTION_KEY = 'tool-defect.oidc.authorization-transaction'

/**
 * 只保存完成一次授权跳转所必需的状态和校验器，不保存任何令牌。
 * `take` 先删除再解析，保证回调只能消费一次。
 */
export class SessionStorageAuthorizationTransactionStore
  implements AuthorizationTransactionStore
{
  constructor(private readonly storage: Storage) {}

  save(transaction: AuthorizationTransaction): void {
    this.storage.setItem(TRANSACTION_KEY, JSON.stringify(transaction))
  }

  take(): AuthorizationTransaction | null {
    const encoded = this.storage.getItem(TRANSACTION_KEY)
    this.storage.removeItem(TRANSACTION_KEY)
    if (encoded === null) {
      return null
    }
    try {
      const value: unknown = JSON.parse(encoded)
      if (!isRecord(value)) {
        return null
      }
      const state = stringField(value, 'state')
      const codeVerifier = stringField(value, 'codeVerifier')
      const redirectAfterLogin = stringField(value, 'redirectAfterLogin')
      if (
        state === null ||
        codeVerifier === null ||
        redirectAfterLogin === null
      ) {
        return null
      }
      return { state, codeVerifier, redirectAfterLogin }
    } catch {
      return null
    }
  }
}

/** OIDC 协议适配，令牌响应解析后立即交给内存会话。 */
export class OidcSessionProvider implements TokenRefreshProvider {
  constructor(private readonly transport: OidcTransport) {}

  exchange(code: string, codeVerifier: string): Promise<AuthSession> {
    if (code.length === 0 || codeVerifier.length < 43) {
      return Promise.reject(new Error('TD-AUTH-VALIDATION-001'))
    }
    return this.transport.exchangeAuthorizationCode(code, codeVerifier)
  }

  refresh(refreshToken: string | undefined): Promise<AuthTokens> {
    return this.transport.refresh(refreshToken)
  }

  revoke(refreshToken: string | undefined): Promise<void> {
    return this.transport.revoke(refreshToken)
  }
}

export class HttpOidcTransport implements OidcTransport {
  private readonly fetcher: typeof fetch
  private readonly clock: () => number

  constructor(
    private readonly configuration: OidcClientConfiguration,
    options: {
      readonly fetcher?: typeof fetch
      readonly clock?: () => number
    } = {},
  ) {
    this.fetcher = options.fetcher ?? fetch
    this.clock = options.clock ?? Date.now
  }

  async exchangeAuthorizationCode(
    code: string,
    codeVerifier: string,
  ): Promise<AuthSession> {
    const form = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      code_verifier: codeVerifier,
      client_id: this.configuration.clientId,
      redirect_uri: this.configuration.redirectUri,
    })
    const tokens = await this.requestTokens(form)
    const identity = await this.requestIdentity(tokens.accessToken)
    return { identity, tokens }
  }

  async refresh(refreshToken: string | undefined): Promise<AuthTokens> {
    if (refreshToken === undefined || refreshToken.length === 0) {
      throw new Error('TD-AUTH-REFRESH-TOKEN-001')
    }
    const form = new URLSearchParams({
      grant_type: 'refresh_token',
      refresh_token: refreshToken,
      client_id: this.configuration.clientId,
    })
    return this.requestTokens(form, refreshToken)
  }

  async revoke(refreshToken: string | undefined): Promise<void> {
    if (refreshToken === undefined || refreshToken.length === 0) {
      return
    }
    const endpoint = this.configuration.revocationEndpoint
    if (endpoint === undefined) {
      throw new Error('TD-AUTH-REVOCATION-CONFIG-001')
    }
    const response = await this.fetcher(endpoint, {
      method: 'POST',
      credentials: 'omit',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        token: refreshToken,
        token_type_hint: 'refresh_token',
        client_id: this.configuration.clientId,
      }),
    })
    if (!response.ok) {
      throw new Error(`TD-AUTH-REVOCATION-${response.status}`)
    }
  }

  private async requestTokens(
    form: URLSearchParams,
    previousRefreshToken?: string,
  ): Promise<AuthTokens> {
    const response = await this.fetcher(this.configuration.tokenEndpoint, {
      method: 'POST',
      credentials: 'omit',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: form,
    })
    if (!response.ok) {
      throw new Error(`TD-AUTH-TOKEN-${response.status}`)
    }
    const raw: unknown = await response.json()
    if (!isRecord(raw)) {
      throw new Error('TD-AUTH-TOKEN-RESPONSE-001')
    }
    const accessToken = stringField(raw, 'access_token')
    const expiresIn = numberField(raw, 'expires_in')
    if (accessToken === null || expiresIn === null || expiresIn <= 0) {
      throw new Error('TD-AUTH-TOKEN-RESPONSE-001')
    }
    const responseRefreshToken = stringField(raw, 'refresh_token')
    const refreshToken = responseRefreshToken ?? previousRefreshToken
    return {
      accessToken,
      ...(refreshToken === undefined ? {} : { refreshToken }),
      expiresAtEpochMs: this.clock() + expiresIn * 1_000,
    }
  }

  private async requestIdentity(accessToken: string): Promise<AuthIdentity> {
    const response = await this.fetcher(this.configuration.userInfoEndpoint, {
      method: 'GET',
      credentials: 'omit',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
    })
    if (!response.ok) {
      throw new Error(`TD-AUTH-USERINFO-${response.status}`)
    }
    const raw: unknown = await response.json()
    if (!isRecord(raw)) {
      throw new Error('TD-AUTH-USERINFO-RESPONSE-001')
    }
    const subject = stringField(raw, 'sub')
    if (subject === null) {
      throw new Error('TD-AUTH-USERINFO-RESPONSE-001')
    }
    const displayName =
      stringField(raw, 'name') ??
      stringField(raw, 'preferred_username') ??
      subject
    return {
      subject,
      displayName,
      roles: stringList(raw.roles),
      permissions: permissionList(raw),
    }
  }
}

export class OidcAuthorizationCoordinator {
  private readonly randomBytes: (length: number) => Uint8Array
  private readonly digest: (value: BufferSource) => Promise<ArrayBuffer>

  constructor(
    private readonly configuration: OidcClientConfiguration,
    private readonly provider: OidcSessionProvider,
    private readonly transactions: AuthorizationTransactionStore,
    options: {
      readonly randomBytes?: (length: number) => Uint8Array
      readonly digest?: (value: BufferSource) => Promise<ArrayBuffer>
    } = {},
  ) {
    this.randomBytes =
      options.randomBytes ??
      ((length) => globalThis.crypto.getRandomValues(new Uint8Array(length)))
    this.digest =
      options.digest ??
      ((value) => globalThis.crypto.subtle.digest('SHA-256', value))
  }

  async createAuthorizationRequest(redirectAfterLogin: string): Promise<string> {
    const state = base64Url(this.randomBytes(32))
    const codeVerifier = base64Url(this.randomBytes(64))
    const challenge = base64Url(
      new Uint8Array(
        await this.digest(new TextEncoder().encode(codeVerifier)),
      ),
    )
    const safeRedirect = normalizeInternalRedirect(redirectAfterLogin)
    this.transactions.save({ state, codeVerifier, redirectAfterLogin: safeRedirect })

    const target = new URL(this.configuration.authorizationEndpoint)
    target.searchParams.set('response_type', 'code')
    target.searchParams.set('client_id', this.configuration.clientId)
    target.searchParams.set('redirect_uri', this.configuration.redirectUri)
    target.searchParams.set('scope', this.configuration.scopes.join(' '))
    target.searchParams.set('state', state)
    target.searchParams.set('code_challenge', challenge)
    target.searchParams.set('code_challenge_method', 'S256')
    return target.toString()
  }

  async completeAuthorizationCallback(
    callbackUrl: string,
  ): Promise<AuthorizationCallbackResult> {
    const transaction = this.transactions.take()
    if (transaction === null) {
      throw new Error('TD-AUTH-TRANSACTION-001')
    }
    const callback = new URL(callbackUrl)
    const expectedCallback = new URL(this.configuration.redirectUri)
    if (
      callback.origin !== expectedCallback.origin ||
      callback.pathname !== expectedCallback.pathname
    ) {
      throw new Error('TD-AUTH-CALLBACK-URI-001')
    }
    const providerError = callback.searchParams.get('error')
    if (providerError !== null) {
      throw new Error('TD-AUTH-PROVIDER-001')
    }
    const state = callback.searchParams.get('state')
    const code = callback.searchParams.get('code')
    if (state === null || !constantTimeEqual(state, transaction.state)) {
      throw new Error('TD-AUTH-STATE-001')
    }
    if (code === null || code.length === 0) {
      throw new Error('TD-AUTH-CODE-001')
    }
    const session = await this.provider.exchange(code, transaction.codeVerifier)
    return {
      session,
      redirectAfterLogin: normalizeInternalRedirect(
        transaction.redirectAfterLogin,
      ),
    }
  }
}

export function normalizeInternalRedirect(value: string): string {
  return value.startsWith('/') && !value.startsWith('//')
    ? value
    : '/workstation'
}

function permissionList(value: Record<string, unknown>): readonly string[] {
  const explicit = stringList(value.permissions)
  if (explicit.length > 0) {
    return explicit
  }
  const scope = stringField(value, 'scope')
  return scope === null ? [] : scope.split(/\s+/).filter(Boolean)
}

function stringList(value: unknown): readonly string[] {
  if (Array.isArray(value)) {
    return value.filter((entry): entry is string => typeof entry === 'string')
  }
  return typeof value === 'string' ? value.split(/\s+/).filter(Boolean) : []
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) {
    return false
  }
  let difference = 0
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index)
  }
  return difference === 0
}

function base64Url(bytes: Uint8Array): string {
  let binary = ''
  for (const value of bytes) {
    binary += String.fromCharCode(value)
  }
  return btoa(binary)
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replace(/=+$/, '')
}

function numberField(
  value: Readonly<Record<string, unknown>>,
  key: string,
): number | null {
  return typeof value[key] === 'number' && Number.isFinite(value[key])
    ? value[key]
    : null
}

function stringField(
  value: Readonly<Record<string, unknown>>,
  key: string,
): string | null {
  return typeof value[key] === 'string' ? value[key] : null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
