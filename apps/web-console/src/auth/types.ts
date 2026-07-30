export interface AuthTokens {
  readonly accessToken: string
  readonly refreshToken?: string
  readonly expiresAtEpochMs: number
}

export interface AuthIdentity {
  readonly subject: string
  readonly displayName: string
  readonly roles: readonly string[]
  readonly permissions: readonly string[]
}

export interface AuthSession {
  readonly identity: AuthIdentity
  readonly tokens: AuthTokens
}

export interface TokenRefreshProvider {
  refresh(refreshToken: string | undefined): Promise<AuthTokens>
}
