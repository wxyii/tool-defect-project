<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { localRequest } from '@/auth/local-auth'

interface UserRow {
  user_id: string
  username: string | null
  display_name: string
  status: 'ACTIVE' | 'DISABLED'
  password_change_required: boolean
  roles: string[]
}

const users = ref<UserRow[]>([])
const username = ref('')
const displayName = ref('')
const initialPassword = ref('')
const role = ref('OPERATOR')
const error = ref<string | null>(null)
const resetPasswords = ref<Record<string, string>>({})

async function load(): Promise<void> {
  const response = await localRequest('/api/v1/users')
  if (!response.ok) throw new Error('TD-USERS-LIST-001')
  const body = await response.json() as { items: UserRow[] }
  users.value = body.items
}

async function create(): Promise<void> {
  error.value = null
  const response = await localRequest('/api/v1/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username: username.value,
      display_name: displayName.value,
      initial_password: initialPassword.value,
      roles: [role.value],
    }),
  })
  if (!response.ok) {
    error.value = '创建账号失败，请检查账号、密码和重复状态'
    return
  }
  username.value = ''
  displayName.value = ''
  initialPassword.value = ''
  await load()
}

async function toggle(user: UserRow): Promise<void> {
  await localRequest(`/api/v1/users/${user.user_id}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      status: user.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE',
    }),
  })
  await load()
}

async function updateRole(user: UserRow, nextRole: string): Promise<void> {
  await localRequest(`/api/v1/users/${user.user_id}/roles`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ roles: [nextRole] }),
  })
  await load()
}

async function resetPassword(user: UserRow): Promise<void> {
  const password = resetPasswords.value[user.user_id] ?? ''
  const response = await localRequest(
    `/api/v1/users/${user.user_id}/password-reset`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ temporary_password: password }),
    },
  )
  if (!response.ok) {
    error.value = '临时密码重置失败'
    return
  }
  resetPasswords.value[user.user_id] = ''
  await load()
}

onMounted(() => void load().catch(() => {
  error.value = '账号列表加载失败'
}))
</script>

<template>
  <section class="page-stack">
    <header>
      <p class="eyebrow">权限管理</p>
      <h2>本地账号</h2>
    </header>
    <form class="panel" @submit.prevent="create">
      <h3>创建账号</h3>
      <label>账号<input v-model="username" minlength="3" maxlength="64" required /></label>
      <label>显示名称<input v-model="displayName" maxlength="256" required /></label>
      <label>初始密码<input v-model="initialPassword" type="password" minlength="12" maxlength="128" required /></label>
      <label>角色
        <select v-model="role">
          <option v-for="value in ['OPERATOR','REVIEWER','QUALITY_MANAGER','ALGORITHM_ENGINEER','MODEL_APPROVER','SYSTEM_OPERATOR','SECURITY_ADMIN','AUDITOR']" :key="value">
            {{ value }}
          </option>
        </select>
      </label>
      <p v-if="error" class="error-code" role="alert">{{ error }}</p>
      <button class="primary-button" type="submit">创建</button>
    </form>
    <div class="panel">
      <table>
        <thead><tr><th>账号</th><th>名称</th><th>状态</th><th>角色</th><th>初始改密</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="user in users" :key="user.user_id">
            <td>{{ user.username ?? '旧账号' }}</td>
            <td>{{ user.display_name }}</td>
            <td>{{ user.status }}</td>
            <td>
              <select :value="user.roles[0]" @change="updateRole(user, ($event.target as HTMLSelectElement).value)">
                <option v-for="value in ['OPERATOR','REVIEWER','QUALITY_MANAGER','ALGORITHM_ENGINEER','MODEL_APPROVER','SYSTEM_OPERATOR','SECURITY_ADMIN','AUDITOR']" :key="value">
                  {{ value }}
                </option>
              </select>
            </td>
            <td>{{ user.password_change_required ? '是' : '否' }}</td>
            <td>
              <button
                class="text-button"
                type="button"
                :disabled="user.username === null"
                @click="toggle(user)"
              >
                {{ user.status === 'ACTIVE' ? '停用' : '启用' }}
              </button>
              <input
                v-model="resetPasswords[user.user_id]"
                type="password"
                minlength="12"
                maxlength="128"
                placeholder="临时密码"
              />
              <button class="text-button" type="button" @click="resetPassword(user)">
                重置密码
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
