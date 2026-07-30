import type { Pinia } from 'pinia'
import {
  createRouter,
  createWebHistory,
  type Router,
} from 'vue-router'

import { createAuthorizationGuard } from './guard'
import { applicationRoutes } from './routes'

export function createApplicationRouter(pinia: Pinia): Router {
  const router = createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes: [...applicationRoutes],
    scrollBehavior: () => ({ top: 0 }),
  })
  router.beforeEach(createAuthorizationGuard(pinia))
  return router
}
