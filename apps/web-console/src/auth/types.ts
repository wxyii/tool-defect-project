export interface AuthIdentity {
  readonly userId?: string
  readonly username?: string
  readonly subject?: string
  readonly displayName: string
  readonly roles: readonly string[]
  readonly permissions: readonly string[]
  readonly passwordChangeRequired?: boolean
}

/** 仅供旧测试替身兼容；生产认证不再使用浏览器令牌。 */
export interface AuthTokens {
  readonly accessToken: string
  readonly refreshToken?: string
  readonly expiresAtEpochMs: number
}

export interface AuthSession {
  readonly identity: AuthIdentity
  readonly tokens: AuthTokens
}

export interface TokenRefreshProvider {
  refresh(refreshToken: string | undefined): Promise<AuthTokens>
}
