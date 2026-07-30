<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { bootstrapOidcCallback } from '@/auth/bootstrap'
import { useOidcRuntime } from '@/auth/runtime'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const errorCode = ref<string | null>(null)
const callbackAbort = new AbortController()

onUnmounted(() => {
  callbackAbort.abort()
})

onMounted(async () => {
  const callbackUrl = window.location.href
  window.history.replaceState(null, '', route.path)
  try {
    const redirect = await bootstrapOidcCallback(
      useOidcRuntime(),
      auth,
      callbackUrl,
      callbackAbort.signal,
    )
    await router.replace(redirect)
  } catch (error) {
    if (callbackAbort.signal.aborted) {
      return
    }
    errorCode.value =
      error instanceof Error && error.message.startsWith('TD-AUTH-')
        ? error.message
        : 'TD-AUTH-CALLBACK-001'
  }
})
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-live="polite">
      <p class="eyebrow">统一身份认证</p>
      <h1>{{ errorCode === null ? '正在建立安全会话' : '登录未完成' }}</h1>
      <p v-if="errorCode === null">正在校验授权回调，请稍候。</p>
      <template v-else>
        <p>认证信息无效或已过期，请重新登录。</p>
        <p class="error-code">错误码：{{ errorCode }}</p>
        <RouterLink class="primary-button inline-button" to="/login">
          返回登录
        </RouterLink>
      </template>
    </section>
  </main>
</template>
