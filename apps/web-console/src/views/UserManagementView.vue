<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { localRequest } from '@/auth/local-auth'
import type { PersonRole } from '@/auth/types'

const PERSON_ROLES: readonly PersonRole[] = [
  'PRODUCTION_EMPLOYEE',
  'ADMINISTRATOR',
]

interface UserRow {
  user_id: string
  username: string | null
  display_name: string
  status: 'ACTIVE' | 'DISABLED'
  password_change_required: boolean
  roles: PersonRole[]
}

interface RoleMigrationRow {
  user_id: string
  username: string | null
  display_name: string
  status: 'ACTIVE' | 'DISABLED'
  legacy_roles: string[]
  suggested_role: PersonRole | null
  selected_role: PersonRole | null
  migration_status: 'UNCONFIRMED' | 'CONFIRMED' | 'CONFLICT' | 'REJECTED'
  decision_reason: string | null
}

const users = ref<UserRow[]>([])
const migrations = ref<RoleMigrationRow[]>([])
const username = ref('')
const displayName = ref('')
const initialPassword = ref('')
const role = ref<PersonRole>('PRODUCTION_EMPLOYEE')
const error = ref<string | null>(null)
const resetPasswords = ref<Record<string, string>>({})
const displayNameDrafts = ref<Record<string, string>>({})
const migrationReasons = ref<Record<string, string>>({})

function migrationFor(userId: string): RoleMigrationRow | undefined {
  return migrations.value.find((item) => item.user_id === userId)
}

async function load(): Promise<void> {
  const [usersResponse, migrationsResponse] = await Promise.all([
    localRequest('/api/v1/users'),
    localRequest('/api/v1/users/role-migration-preview'),
  ])
  if (!usersResponse.ok || !migrationsResponse.ok) {
    throw new Error('TD-USERS-LIST-001')
  }
  const body = await usersResponse.json() as { items: UserRow[] }
  const migrationBody = await migrationsResponse.json() as { items: RoleMigrationRow[] }
  users.value = body.items
  migrations.value = migrationBody.items
  displayNameDrafts.value = Object.fromEntries(
    users.value.map((user) => [user.user_id, user.display_name]),
  )
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
  const migration = migrationFor(user.user_id)
  const isMigration = migration !== undefined
    && migration.migration_status !== 'CONFIRMED'
  const response = await localRequest(isMigration
    ? `/api/v1/users/${user.user_id}/role-migration`
    : `/api/v1/users/${user.user_id}/roles`, {
    method: isMigration ? 'POST' : 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(isMigration
      ? {
          role: nextRole,
          reason: migrationReasons.value[user.user_id] ?? '',
        }
      : { roles: [nextRole] }),
  })
  if (!response.ok) {
    error.value = isMigration
      ? '角色迁移确认失败，请补充原因或处理冲突'
      : '角色更新失败'
    return
  }
  await load()
}

async function updateDisplayName(user: UserRow): Promise<void> {
  const nextName = displayNameDrafts.value[user.user_id] ?? ''
  const response = await localRequest(`/api/v1/users/${user.user_id}/display-name`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: nextName }),
  })
  if (!response.ok) {
    error.value = '显示名称更新失败'
    return
  }
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
          <option v-for="value in PERSON_ROLES" :key="value">
            {{ value }}
          </option>
        </select>
      </label>
      <p v-if="error" class="error-code" role="alert">{{ error }}</p>
      <button class="primary-button" type="submit">创建</button>
    </form>
    <div class="panel">
      <table>
        <thead><tr><th>账号</th><th>名称</th><th>状态</th><th>角色迁移</th><th>角色</th><th>初始改密</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="user in users" :key="user.user_id">
            <td>{{ user.username ?? '旧账号' }}</td>
            <td>
              <input
                v-model="displayNameDrafts[user.user_id]"
                maxlength="256"
                aria-label="显示名称"
              />
              <button class="text-button" type="button" @click="updateDisplayName(user)">保存名称</button>
            </td>
            <td>{{ user.status }}</td>
            <td>
              <span v-if="migrationFor(user.user_id)">
                {{ migrationFor(user.user_id)?.migration_status }}
                <small v-if="migrationFor(user.user_id)?.legacy_roles.length">
                  旧角色：{{ migrationFor(user.user_id)?.legacy_roles.join('、') }}
                </small>
              </span>
              <span v-else>已确认账号</span>
              <input
                v-if="migrationFor(user.user_id) && migrationFor(user.user_id)?.migration_status !== 'CONFIRMED'"
                v-model="migrationReasons[user.user_id]"
                maxlength="1024"
                placeholder="迁移确认原因"
                aria-label="迁移确认原因"
              />
            </td>
            <td>
              <select :value="user.roles[0] ?? migrationFor(user.user_id)?.selected_role ?? migrationFor(user.user_id)?.suggested_role ?? ''" @change="updateRole(user, ($event.target as HTMLSelectElement).value)">
                <option v-for="value in PERSON_ROLES" :key="value">
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
