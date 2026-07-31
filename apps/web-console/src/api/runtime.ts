import type { useAuthStore } from '@/stores/auth'

import { ApiClient } from './client'

let currentClient: ApiClient | null = null

export function configureApplicationApiClient(
  environment: ImportMetaEnv,
  origin: string,
  auth: ReturnType<typeof useAuthStore>,
  fetcher: typeof fetch = (input, init) => window.fetch(input, init),
): ApiClient {
  const client = new ApiClient({
    baseUrl: environment.VITE_API_BASE_URL?.trim() || origin,
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
