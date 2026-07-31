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

const currentLabel = computed(() => {
  if (route.meta.menuLabel !== undefined) return String(route.meta.menuLabel)
  if (route.name === 'detection-detail') return '检测详情'
  if (route.name === 'review-workbench') return '复核工作台'
  return '受控工作区'
})

const avatarInitial = computed(() =>
  (auth.identity?.displayName ?? '未').trim().slice(0, 1),
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
      <div class="brand">
        <span class="brand-mark" aria-hidden="true"></span>
        <span class="brand-text">
          <strong>刀具缺陷检测系统</strong>
          <small>TOOL DEFECT VISION CONSOLE</small>
        </span>
      </div>
      <nav class="top-nav" aria-label="主导航">
        <RouterLink
          v-for="item in menuItems"
          :key="String(item.name)"
          :to="item.path"
          class="nav-link"
        >
          {{ item.meta?.menuLabel }}
        </RouterLink>
      </nav>
      <div class="topbar-actions">
        <span class="connection" aria-label="中心连接正常">
          <span class="status-dot" aria-hidden="true"></span>
          中心在线
        </span>
        <span class="avatar" aria-hidden="true">{{ avatarInitial }}</span>
        <span class="username">{{ auth.identity?.displayName ?? '未登录' }}</span>
        <button type="button" class="text-button" @click="signOut">退出</button>
      </div>
    </header>

    <div class="crumb" aria-label="当前位置">
      <span class="crumb-home">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11 12 3l9 8v10h-6v-6H9v6H3z"/></svg>
        首页
      </span>
      <span class="crumb-sep" aria-hidden="true">/</span>
      <span class="crumb-current">{{ currentLabel }}</span>
    </div>

    <main class="content" tabindex="-1">
      <RouterView />
    </main>
  </div>
</template>
