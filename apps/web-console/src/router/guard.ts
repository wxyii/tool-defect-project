import type { Pinia } from 'pinia'
import type { RouteLocationNormalized } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

export function createAuthorizationGuard(pinia: Pinia) {
  return (to: RouteLocationNormalized) => {
    const auth = useAuthStore(pinia)
    if (!to.meta.requiresAuth) {
      return true
    }
    if (!auth.authenticated) {
      return {
        name: 'login',
        query: { redirect: safeRedirect(to.fullPath) },
      }
    }
    if (
      auth.identity?.passwordChangeRequired
      && to.name !== 'change-password'
    ) {
      return { name: 'change-password' }
    }
    if (
      !auth.identity?.passwordChangeRequired
      && to.name === 'change-password'
    ) {
      return { name: 'workstation' }
    }
    const permissions = to.meta.permissions ?? []
    if (!auth.hasEveryPermission(permissions)) {
      return to.name === 'unauthorized' ? true : { name: 'unauthorized' }
    }
    return true
  }
}

function safeRedirect(value: string): string {
  return value.startsWith('/') && !value.startsWith('//')
    ? value
    : '/workstation'
}
