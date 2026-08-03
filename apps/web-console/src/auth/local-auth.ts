import type { AuthIdentity, PersonRole } from './types'

let csrfToken: string | null = null

export async function ensureCsrf(fetcher: typeof fetch = fetch): Promise<string> {
  if (csrfToken !== null) {
    return csrfToken
  }
  const response = await fetcher('/api/v1/auth/csrf', {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error('TD-AUTH-CSRF-001')
  }
  const body = await response.json() as { token?: unknown }
  if (typeof body.token !== 'string') {
    throw new Error('TD-AUTH-CSRF-001')
  }
  csrfToken = body.token
  return csrfToken
}

export async function localRequest(
  path: string,
  init: RequestInit = {},
  fetcher: typeof fetch = fetch,
): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    headers.set('X-TD-CSRF', await ensureCsrf(fetcher))
    if (!headers.has('Idempotency-Key')) {
      headers.set('Idempotency-Key', crypto.randomUUID())
    }
  }
  return fetcher(path, {
    ...init,
    credentials: 'same-origin',
    headers,
  })
}

export async function login(
  username: string,
  password: string,
): Promise<AuthIdentity> {
  const response = await localRequest('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!response.ok) {
    throw new Error(response.status === 401
      ? 'TD-AUTH-UNAUTHORIZED-001'
      : 'TD-AUTH-LOGIN-001')
  }
  return parseIdentity(await response.json())
}

export async function restoreSession(): Promise<AuthIdentity | null> {
  const response = await localRequest('/api/v1/auth/session')
  if (response.status === 401) {
    return null
  }
  if (!response.ok) {
    throw new Error('TD-AUTH-SESSION-001')
  }
  return parseIdentity(await response.json())
}

export async function logout(): Promise<void> {
  await localRequest('/api/v1/auth/logout', { method: 'POST' })
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const response = await localRequest('/api/v1/auth/password/change', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  })
  if (!response.ok) {
    throw new Error(response.status === 401
      ? 'TD-AUTH-UNAUTHORIZED-001'
      : 'TD-AUTH-PASSWORD-001')
  }
}

export function parseIdentity(value: unknown): AuthIdentity {
  if (value === null || typeof value !== 'object') {
    throw new Error('TD-AUTH-RESPONSE-001')
  }
  const data = value as Record<string, unknown>
  if (
    typeof data.user_id !== 'string'
    || typeof data.username !== 'string'
    || typeof data.display_name !== 'string'
    || !Array.isArray(data.roles)
    || !Array.isArray(data.permissions)
    || typeof data.password_change_required !== 'boolean'
  ) {
    throw new Error('TD-AUTH-RESPONSE-001')
  }
  const roles = data.roles.filter(
    (role): role is PersonRole =>
      role === 'PRODUCTION_EMPLOYEE' || role === 'ADMINISTRATOR',
  )
  if (roles.length !== data.roles.length || roles.length > 1) {
    throw new Error('TD-AUTH-RESPONSE-001')
  }
  return Object.freeze({
    userId: data.user_id,
    username: data.username,
    displayName: data.display_name,
    roles: Object.freeze(roles),
    permissions: Object.freeze(data.permissions.map(String)),
    passwordChangeRequired: data.password_change_required,
  })
}
