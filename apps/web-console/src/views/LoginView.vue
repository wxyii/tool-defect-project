<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { login } from '@/auth/local-auth'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const username = ref('')
const password = ref('')
const redirect = computed(() =>
  typeof route.query.redirect === 'string'
    && route.query.redirect.startsWith('/')
    && !route.query.redirect.startsWith('//')
    ? route.query.redirect
    : '/workstation',
)
const busy = ref(false)
const errorCode = ref<string | null>(null)

async function beginLogin(): Promise<void> {
  busy.value = true
  errorCode.value = null
  try {
    const identity = await login(username.value, password.value)
    auth.establish(identity)
    await router.replace(
      identity.passwordChangeRequired ? '/change-password' : redirect.value,
    )
  } catch (error) {
    busy.value = false
    errorCode.value =
      error instanceof Error && error.message.startsWith('TD-AUTH-')
        ? error.message
        : 'TD-AUTH-LOGIN-001'
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <header class="login-brand">
        <span class="login-brand__mark" aria-hidden="true"></span>
        <span class="login-brand__text">
          <strong>刀具缺陷检测系统</strong>
          <small>TOOL DEFECT VISION CONSOLE</small>
        </span>
      </header>
      <p class="eyebrow">受控质量系统</p>
      <h1 id="login-title">登录刀具缺陷检测平台</h1>
      <p>使用本系统账号和密码登录。</p>
      <p v-if="errorCode !== null" class="error-code" role="alert">
        账号或密码不正确，或账号当前不可用（{{ errorCode }}）
      </p>
      <form @submit.prevent="beginLogin">
        <label>
          账号
          <input
            v-model="username"
            name="username"
            autocomplete="username"
            minlength="3"
            maxlength="64"
            required
          />
        </label>
        <label>
          密码
          <input
            v-model="password"
            name="password"
            type="password"
            autocomplete="current-password"
            minlength="12"
            maxlength="128"
            required
          />
        </label>
        <button
          type="submit"
          class="primary-button"
          :disabled="busy"
        >
          {{ busy ? '正在登录…' : '登录' }}
        </button>
      </form>
    </section>
  </main>
</template>
