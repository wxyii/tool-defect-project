<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { changePassword } from '@/auth/local-auth'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const currentPassword = ref('')
const newPassword = ref('')
const confirmation = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

async function submit(): Promise<void> {
  if (newPassword.value !== confirmation.value) {
    error.value = '两次输入的新密码不一致'
    return
  }
  busy.value = true
  error.value = null
  try {
    await changePassword(currentPassword.value, newPassword.value)
    auth.clear()
    await router.replace({ name: 'login' })
  } catch {
    error.value = '密码修改失败，请检查当前密码和新密码要求'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="password-title">
      <p class="eyebrow">账号安全</p>
      <h1 id="password-title">修改密码</h1>
      <p>新密码长度为 12～128 个字符，且不能与账号相同。</p>
      <p v-if="error" class="error-code" role="alert">{{ error }}</p>
      <form @submit.prevent="submit">
        <label>当前密码
          <input v-model="currentPassword" type="password" autocomplete="current-password" required />
        </label>
        <label>新密码
          <input v-model="newPassword" type="password" autocomplete="new-password" minlength="12" maxlength="128" required />
        </label>
        <label>确认新密码
          <input v-model="confirmation" type="password" autocomplete="new-password" minlength="12" maxlength="128" required />
        </label>
        <button class="primary-button" type="submit" :disabled="busy">
          {{ busy ? '正在提交…' : '修改密码并重新登录' }}
        </button>
      </form>
    </section>
  </main>
</template>
