<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { useApplicationApiClient } from '@/api/runtime'

import { AuditService } from './service'
import type { AuditRecordPage, AuditRecordSummary } from './service'

const service = new AuditService(useApplicationApiClient())
const now = new Date()
const page = ref<AuditRecordPage | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const cursors = ref<(string | undefined)[]>([undefined])

const startTime = ref(localInput(new Date(now.getTime() - 24 * 60 * 60 * 1_000)))
const endTime = ref(localInput(now))
const actorId = ref('')
const action = ref('')
const resourceType = ref('')
const resourceId = ref('')
const result = ref('')

const pageNumber = computed(() => cursors.value.length)
const windowLabel = computed(() => {
  const start = new Date(startTime.value)
  const end = new Date(endTime.value)
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) {
    return '时间窗待校验'
  }
  const hours = Math.max(0, (end.getTime() - start.getTime()) / 3_600_000)
  return hours < 48 ? `${hours.toFixed(1)} 小时` : `${(hours / 24).toFixed(1)} 天`
})

onMounted(() => void applyFilters())

async function applyFilters(): Promise<void> {
  cursors.value = [undefined]
  await load(undefined)
}

async function nextPage(): Promise<void> {
  const cursor = page.value?.next_cursor
  if (cursor === null || cursor === undefined) return
  if (await load(cursor)) cursors.value.push(cursor)
}

async function previousPage(): Promise<void> {
  if (cursors.value.length <= 1) return
  const target = cursors.value[cursors.value.length - 2]
  if (await load(target)) cursors.value.pop()
}

async function load(cursor: string | undefined): Promise<boolean> {
  if (loading.value) return false
  loading.value = true
  error.value = null
  try {
    page.value = await service.list({
      pageSize: 50,
      startTime: utc(startTime.value),
      endTime: utc(endTime.value),
      ...(cursor === undefined ? {} : { cursor }),
      ...(actorId.value.trim() === '' ? {} : { actorId: actorId.value }),
      ...(action.value.trim() === '' ? {} : { action: action.value }),
      ...(resourceType.value.trim() === '' ? {} : { resourceType: resourceType.value }),
      ...(resourceId.value.trim() === '' ? {} : { resourceId: resourceId.value }),
      ...(result.value === '' ? {} : { result: result.value }),
    })
    return true
  } catch {
    error.value = '审计记录读取失败。请检查时间范围、筛选条件或服务连接状态。'
    return false
  } finally {
    loading.value = false
  }
}

function resetFilters(): void {
  const current = new Date()
  startTime.value = localInput(new Date(current.getTime() - 24 * 60 * 60 * 1_000))
  endTime.value = localInput(current)
  actorId.value = ''
  action.value = ''
  resourceType.value = ''
  resourceId.value = ''
  result.value = ''
  void applyFilters()
}

function localInput(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function utc(value: string): string {
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.getTime())) throw new Error('时间格式无效')
  return parsed.toISOString()
}

function time(value: string): string {
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function shortId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-6)}`
}

function resultTone(value: string): string {
  const normalized = value.toUpperCase()
  if (normalized === 'SUCCESS' || normalized === 'SUCCEEDED') return 'success'
  if (normalized === 'FAILED' || normalized === 'FAILURE') return 'failed'
  return 'neutral'
}

function resultLabel(value: string): string {
  const tone = resultTone(value)
  if (tone === 'success') return '成功'
  if (tone === 'failed') return '失败'
  return value
}

function actionLabel(value: string): string {
  const labels: Readonly<Record<string, string>> = {
    'audit.records.query': '查询审计记录',
    'review.priority.change': '调整复核优先级',
    'review.revision.open': '创建复核修订',
    'review.training.approve': '批准训练候选',
    'review.training.reject': '拒绝训练候选',
  }
  return labels[value] ?? value
}

function evidencePresent(record: AuditRecordSummary): boolean {
  return record.before_digest !== null || record.after_digest !== null
}
</script>

<template>
  <section class="audit-page">
    <header class="audit-masthead">
      <div>
        <p class="eyebrow">证据分类账 · 只读</p>
        <h2>审计记录</h2>
        <p>按事件发生时间倒序检索不可变操作证据；当前查询行为本身也会被记录。</p>
      </div>
      <div class="immutability-seal" aria-label="只读审计边界">
        <span class="seal-mark" aria-hidden="true">只读</span>
        <div>
          <strong>追加式审计链</strong>
          <small>此界面不提供修改或删除操作</small>
        </div>
      </div>
    </header>

    <form class="audit-filter" aria-label="审计记录筛选" @submit.prevent="applyFilters()">
      <label class="time-field">
        开始时间
        <input v-model="startTime" type="datetime-local" required />
      </label>
      <label class="time-field">
        结束时间
        <input v-model="endTime" type="datetime-local" required />
      </label>
      <label>
        操作人包含
        <input v-model="actorId" type="search" maxlength="256" placeholder="用户标识" />
      </label>
      <label>
        动作包含
        <input v-model="action" type="search" maxlength="128" placeholder="例如 review" />
      </label>
      <label>
        资源类型
        <input v-model="resourceType" type="search" maxlength="128" placeholder="例如 review_task" />
      </label>
      <label>
        资源标识包含
        <input v-model="resourceId" type="search" maxlength="256" placeholder="资源标识" />
      </label>
      <label>
        执行结果
        <select v-model="result">
          <option value="">全部结果</option>
          <option value="SUCCESS">成功</option>
          <option value="SUCCEEDED">已完成</option>
          <option value="FAILED">失败</option>
        </select>
      </label>
      <div class="filter-actions">
        <button type="button" class="secondary-button" @click="resetFilters">重置</button>
        <button type="submit" class="primary-button compact" :disabled="loading">
          {{ loading ? '正在检索' : '检索证据' }}
        </button>
      </div>
      <p class="filter-boundary">
        查询窗 {{ windowLabel }}，单次最多 31 天 · 操作人、动作和资源标识为包含匹配
      </p>
    </form>

    <p v-if="error !== null" class="audit-error" role="alert">{{ error }}</p>

    <section class="ledger-shell" aria-live="polite">
      <header class="ledger-heading">
        <div>
          <span class="ledger-index">第 {{ pageNumber }} 页</span>
          <h3>事件账本</h3>
        </div>
        <span v-if="page !== null">
          本页 {{ page.items.length }} 条 · {{ page.has_more ? '仍有后续记录' : '已到当前窗口末端' }}
        </span>
      </header>

      <div v-if="loading && page === null" class="ledger-state" role="status">
        正在核验并读取审计证据…
      </div>
      <div v-else-if="page !== null && page.items.length === 0" class="ledger-state">
        <strong>当前条件下没有审计事件</strong>
        <span>可扩大时间窗或移除部分筛选条件后重试。</span>
      </div>

      <ol v-else-if="page !== null" class="audit-ledger">
        <li v-for="record in page.items" :key="record.audit_id">
          <details class="audit-entry">
            <summary>
              <span class="event-time">
                <i aria-hidden="true"></i>
                {{ time(record.occurred_at) }}
              </span>
              <span :class="['result-stamp', `result-stamp--${resultTone(record.result)}`]">
                {{ resultLabel(record.result) }}
              </span>
              <span class="actor-cell">
                <small>{{ record.actor_type }}</small>
                <strong>{{ record.actor_id }}</strong>
              </span>
              <span class="action-cell">
                <strong>{{ actionLabel(record.action) }}</strong>
                <code>{{ record.action }}</code>
              </span>
              <span class="resource-cell">
                <small>{{ record.resource_type }}</small>
                <strong>{{ shortId(record.resource_id) }}</strong>
              </span>
              <span class="event-id">{{ shortId(record.audit_id) }}</span>
              <span class="expand-label">展开证据</span>
            </summary>

            <div class="evidence-drawer">
              <div class="evidence-primary">
                <div>
                  <span>事件标识</span>
                  <code>{{ record.audit_id }}</code>
                </div>
                <div>
                  <span>资源</span>
                  <code>{{ record.resource_type }} / {{ record.resource_id }}</code>
                </div>
                <div>
                  <span>操作原因</span>
                  <p>{{ record.reason ?? '未记录操作原因' }}</p>
                </div>
                <div>
                  <span>来源地址</span>
                  <code>{{ record.actor_ip ?? '未采集' }}</code>
                </div>
              </div>
              <div class="digest-chain" :class="{ 'digest-chain--empty': !evidencePresent(record) }">
                <div>
                  <span>变更前摘要</span>
                  <code>{{ record.before_digest ?? '无前态摘要' }}</code>
                </div>
                <i aria-hidden="true">→</i>
                <div>
                  <span>变更后摘要</span>
                  <code>{{ record.after_digest ?? '无后态摘要' }}</code>
                </div>
              </div>
              <dl class="trace-grid">
                <div><dt>请求标识</dt><dd>{{ record.request_id }}</dd></div>
                <div><dt>追踪标识</dt><dd>{{ record.trace_id }}</dd></div>
                <div><dt>错误码</dt><dd>{{ record.error_code ?? '无' }}</dd></div>
                <div><dt>原始结果</dt><dd>{{ record.result }}</dd></div>
              </dl>
            </div>
          </details>
        </li>
      </ol>
    </section>

    <nav v-if="page !== null" class="audit-pager" aria-label="审计记录分页">
      <button
        type="button"
        class="secondary-button"
        :disabled="loading || cursors.length <= 1"
        @click="previousPage"
      >
        上一页
      </button>
      <span>游标分页 · 第 {{ pageNumber }} 页</span>
      <button
        type="button"
        class="secondary-button"
        :disabled="loading || !page.has_more || page.next_cursor === null"
        @click="nextPage"
      >
        下一页
      </button>
    </nav>
  </section>
</template>

<style scoped>
.audit-page {
  display: grid;
  gap: 14px;
  max-width: 1500px;
  margin: 0 auto;
}

.audit-masthead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 30px;
  min-height: 118px;
  padding: 22px 24px 22px 28px;
  border: 1px solid #cfdce7;
  border-left: 5px solid #315b78;
  border-radius: 4px;
  color: #eef8ff;
  background:
    linear-gradient(100deg, rgb(18 54 81 / 98%), rgb(27 73 103 / 96%)),
    repeating-linear-gradient(0deg, transparent 0 27px, rgb(255 255 255 / 5%) 28px);
  box-shadow: var(--shadow-card);
}

.audit-masthead .eyebrow { color: #83c8f5; }
.audit-masthead h2 { margin: 5px 0; color: #fff; font-size: 28px; }
.audit-masthead p:last-child { margin: 0; color: #bed1df; font-size: 12px; }

.immutability-seal {
  display: flex;
  flex: none;
  gap: 12px;
  align-items: center;
  padding: 10px 14px 10px 10px;
  border: 1px solid rgb(147 204 239 / 35%);
  background: rgb(4 38 62 / 42%);
}

.seal-mark {
  display: grid;
  width: 46px;
  height: 46px;
  place-items: center;
  border: 1px solid #7bc3ed;
  border-radius: 50%;
  color: #a8ddfb;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.immutability-seal div { display: grid; gap: 4px; }
.immutability-seal strong { color: #fff; font-size: 12px; }
.immutability-seal small { color: #9fb9cb; font-size: 10px; }

.audit-filter {
  display: grid;
  grid-template-columns: repeat(7, minmax(120px, 1fr)) auto;
  gap: 11px;
  align-items: end;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel);
  box-shadow: var(--shadow-card);
}

.audit-filter label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.07em;
}

.audit-filter input,
.audit-filter select {
  min-width: 0;
  min-height: 38px;
  padding: 7px 9px;
  border: 1px solid var(--line-strong);
  border-radius: 3px;
  color: var(--ink);
  background: #fff;
  font-size: 12px;
}

.time-field { min-width: 185px; }
.filter-actions { display: flex; gap: 7px; }
.filter-actions .secondary-button { white-space: nowrap; }

.filter-boundary {
  grid-column: 1 / -1;
  margin: 2px 0 -2px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
  color: var(--faint);
  font-size: 10.5px;
}

.audit-error {
  margin: 0;
  padding: 12px 16px;
  border: 1px solid var(--danger-line);
  color: var(--danger);
  background: var(--danger-bg);
}

.ledger-shell {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel);
  box-shadow: var(--shadow-card);
}

.ledger-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 58px;
  padding: 11px 18px;
  border-bottom: 1px solid var(--line-strong);
  background: #f7fafc;
}

.ledger-heading > div { display: flex; gap: 11px; align-items: center; }
.ledger-heading h3 { margin: 0; font-size: 14px; }
.ledger-heading > span { color: var(--muted); font-size: 11px; }
.ledger-index { padding: 4px 7px; border: 1px solid #bfd8e8; color: var(--accent-ink); background: var(--accent-soft); font-family: var(--font-mono); font-size: 10px; }

.ledger-state {
  display: grid;
  min-height: 190px;
  place-content: center;
  gap: 7px;
  color: var(--muted);
  text-align: center;
}

.ledger-state strong { color: var(--ink); }
.audit-ledger { margin: 0; padding: 0; list-style: none; }
.audit-ledger > li { border-bottom: 1px solid var(--line); }
.audit-ledger > li:last-child { border-bottom: 0; }

.audit-entry > summary {
  display: grid;
  grid-template-columns: 156px 68px minmax(130px, 0.9fr) minmax(180px, 1.25fr) minmax(150px, 1fr) 118px 72px;
  gap: 13px;
  align-items: center;
  min-height: 72px;
  padding: 10px 17px;
  cursor: pointer;
  list-style: none;
  transition: background 120ms ease;
}

.audit-entry > summary::-webkit-details-marker { display: none; }
.audit-entry > summary:hover { background: #f3f9fd; }
.audit-entry[open] > summary { background: #eef7fc; }

.event-time { display: flex; gap: 8px; align-items: center; color: var(--muted); font-family: var(--font-mono); font-size: 10px; }
.event-time i { width: 8px; height: 8px; border: 2px solid #75a9c9; border-radius: 50%; background: #fff; }

.result-stamp {
  justify-self: start;
  padding: 4px 8px;
  border: 1px solid var(--line-strong);
  border-radius: 2px;
  font-size: 10px;
  font-weight: 700;
}

.result-stamp--success { border-color: var(--success-line); color: var(--success); background: var(--success-bg); }
.result-stamp--failed { border-color: var(--danger-line); color: var(--danger); background: var(--danger-bg); }
.result-stamp--neutral { color: var(--muted); background: var(--well); }

.actor-cell,
.action-cell,
.resource-cell { display: grid; min-width: 0; gap: 4px; }
.actor-cell small,
.resource-cell small { color: var(--faint); font-size: 9.5px; letter-spacing: 0.06em; }
.actor-cell strong,
.resource-cell strong,
.action-cell strong { overflow: hidden; font-size: 11.5px; text-overflow: ellipsis; white-space: nowrap; }
.action-cell code { overflow: hidden; color: var(--muted); font-family: var(--font-mono); font-size: 9.5px; text-overflow: ellipsis; white-space: nowrap; }
.event-id { color: var(--faint); font-family: var(--font-mono); font-size: 9.5px; }
.expand-label { color: var(--accent-deep); font-size: 10px; text-align: right; }
.audit-entry[open] .expand-label { font-size: 0; }
.audit-entry[open] .expand-label::after { font-size: 10px; content: "收起证据"; }

.evidence-drawer {
  padding: 18px 20px 20px 47px;
  border-top: 1px dashed #bfd4e1;
  background: #f8fbfd;
}

.evidence-primary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.evidence-primary > div,
.digest-chain > div {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--line);
  background: #fff;
}

.evidence-primary span,
.digest-chain span { color: var(--faint); font-size: 9.5px; letter-spacing: 0.08em; }
.evidence-primary code,
.digest-chain code { overflow-wrap: anywhere; color: #31566f; font-family: var(--font-mono); font-size: 10px; }
.evidence-primary p { margin: 0; color: var(--ink); font-size: 11px; line-height: 1.55; }

.digest-chain {
  display: grid;
  grid-template-columns: 1fr 28px 1fr;
  gap: 8px;
  align-items: center;
  margin-top: 12px;
}

.digest-chain > i { color: var(--accent); font-family: var(--font-mono); font-size: 20px; font-style: normal; text-align: center; }
.digest-chain--empty { opacity: 0.62; }

.trace-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 12px 0 0;
  background: var(--line);
}

.trace-grid div { min-width: 0; padding: 9px 11px; background: #eef4f8; }
.trace-grid dt { color: var(--faint); font-size: 9px; }
.trace-grid dd { margin: 4px 0 0; overflow-wrap: anywhere; color: var(--muted); font-family: var(--font-mono); font-size: 9.5px; }

.audit-pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 14px;
}

.audit-pager span { color: var(--muted); font-family: var(--font-mono); font-size: 10.5px; }
.audit-pager button:disabled { cursor: not-allowed; opacity: 0.45; }

@media (width <= 1280px) {
  .audit-filter { grid-template-columns: repeat(4, minmax(150px, 1fr)); }
  .audit-entry > summary { grid-template-columns: 150px 65px 1fr 1.2fr 1fr 70px; }
  .event-id { display: none; }
  .evidence-primary { grid-template-columns: repeat(2, 1fr); }
}

@media (width <= 820px) {
  .audit-masthead { align-items: flex-start; flex-direction: column; }
  .audit-filter { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .time-field { min-width: 0; }
  .audit-entry > summary { grid-template-columns: 1fr auto auto; }
  .actor-cell,
  .action-cell,
  .resource-cell { grid-column: 1 / -1; }
  .expand-label { grid-row: 1; grid-column: 3; }
  .evidence-drawer { padding-left: 20px; }
  .trace-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (width <= 520px) {
  .audit-filter,
  .evidence-primary,
  .trace-grid { grid-template-columns: 1fr; }
  .filter-actions { justify-content: flex-end; }
  .digest-chain { grid-template-columns: 1fr; }
  .digest-chain > i { transform: rotate(90deg); }
  .audit-pager { justify-content: space-between; }
  .audit-pager span { display: none; }
}
</style>
