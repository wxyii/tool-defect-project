<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { logout } from '@/auth/local-auth'
import { applicationRoutes } from '@/router/routes'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const menuItems = computed(() =>
  applicationRoutes.filter((item) => {
    const label = item.meta?.menuLabel
    const permissions = item.meta?.permissions ?? []
    return label !== undefined && auth.hasEveryPermission(permissions)
  }),
)

async function signOut(): Promise<void> {
  try {
    await logout()
  } finally {
  auth.clear()
    await router.replace({ name: 'login' })
  }
}
</script>

<template>
  <div v-if="route.meta.standalone" class="standalone">
    <RouterView />
  </div>
  <div v-else class="app-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">刀具缺陷检测系统</p>
        <h1>{{ String(route.meta.menuLabel ?? '受控工作区') }}</h1>
      </div>
      <div class="topbar-actions">
        <span class="connection" aria-label="中心连接正常">
          <span class="status-dot" aria-hidden="true"></span>
          中心在线
        </span>
        <span>{{ auth.identity?.displayName ?? '未登录' }}</span>
        <button type="button" class="text-button" @click="signOut">退出</button>
      </div>
    </header>

    <aside class="sidebar" aria-label="主导航">
      <nav>
        <RouterLink
          v-for="item in menuItems"
          :key="String(item.name)"
          :to="item.path"
          class="nav-link"
        >
          <span aria-hidden="true">{{ item.meta?.menuIcon }}</span>
          <span>{{ item.meta?.menuLabel }}</span>
        </RouterLink>
      </nav>
      <p class="sidebar-note">权限由后端强制校验</p>
    </aside>

    <main class="content" tabindex="-1">
      <RouterView />
    </main>
  </div>
</template>
