/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_OIDC_AUTHORIZATION_ENDPOINT?: string
  readonly VITE_OIDC_TOKEN_ENDPOINT?: string
  readonly VITE_OIDC_USERINFO_ENDPOINT?: string
  readonly VITE_OIDC_REVOCATION_ENDPOINT?: string
  readonly VITE_OIDC_CLIENT_ID?: string
  readonly VITE_OIDC_REDIRECT_URI?: string
  readonly VITE_OIDC_SCOPES?: string
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'

  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>
  export default component
}
