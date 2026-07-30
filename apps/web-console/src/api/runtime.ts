import { useOidcRuntime } from '@/auth/runtime'
import type { SessionEstablisher } from '@/auth/bootstrap'

import { ApiClient } from './client'

let currentClient: ApiClient | null = null

export function configureApplicationApiClient(
  environment: ImportMetaEnv,
  origin: string,
  auth: SessionEstablisher,
  fetcher: typeof fetch = fetch,
): ApiClient {
  const client = new ApiClient({
    baseUrl: environment.VITE_API_BASE_URL?.trim() || origin,
    refreshProvider: useOidcRuntime().refreshProvider,
    fetcher,
    onAuthenticationFailure: () => auth.clear(),
  })
  currentClient = client
  return client
}

export function useApplicationApiClient(): ApiClient {
  if (currentClient === null) {
    throw new Error('TD-API-CONFIG-001')
  }
  return currentClient
}
