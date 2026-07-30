<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { normalizeInternalRedirect } from '@/auth/oidc'
import { useOidcRuntime } from '@/auth/runtime'

const route = useRoute()
const redirect = computed(() =>
  typeof route.query.redirect === 'string'
    ? normalizeInternalRedirect(route.query.redirect)
    : '/workstation',
)
const busy = ref(false)
const errorCode = ref<string | null>(null)

async function beginLogin(): Promise<void> {
  busy.value = true
  errorCode.value = null
  try {
    const target = await useOidcRuntime().createAuthorizationRequest(redirect.value)
    window.location.assign(target)
  } catch (error) {
    busy.value = false
    errorCode.value =
      error instanceof Error && error.message.startsWith('TD-AUTH-')
        ? error.message
        : 'TD-AUTH-START-001'
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <p class="eyebrow">受控质量系统</p>
      <h1 id="login-title">登录刀具缺陷检测平台</h1>
      <p>使用企业统一身份登录。令牌不会写入浏览器长期存储。</p>
      <p v-if="errorCode !== null" class="error-code" role="alert">
        登录配置或身份服务不可用（{{ errorCode }}）
      </p>
      <button
        type="button"
        class="primary-button"
        :disabled="busy"
        @click="beginLogin"
      >
        {{ busy ? '正在跳转…' : '使用统一身份登录' }}
      </button>
    </section>
  </main>
</template>
