<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { DatasetVersionPage, DatasetVersionSummary } from './service'
import { DatasetService } from './service'
import { useApplicationApiClient } from '@/api/runtime'

const service = new DatasetService(useApplicationApiClient())
const page = ref<DatasetVersionPage | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const datasetId = ref('')
const selectedForDiff = ref<Set<string>>(new Set())
const diffResult = ref<Awaited<ReturnType<typeof service.diffVersions>> | null>(null)
const diffing = ref(false)

onMounted(() => void load())

async function load(cursor?: string): Promise<void> {
  if (datasetId.value.trim() === '') {
    error.value = '请先输入数据集 ID'
    return
  }
  loading.value = true
  error.value = null
  try {
    page.value = await service.listVersions(datasetId.value.trim(), {
      pageSize: 25,
      ...(cursor === undefined ? {} : { cursor }),
    })
  } catch {
    error.value = '数据集版本列表暂时无法读取'
  } finally {
    loading.value = false
  }
}

function stateLabel(state: DatasetVersionSummary['status']): string {
  if (state === 'BUILDING') return '构建中'
  if (state === 'VALIDATING') return '校验中'
  if (state === 'FROZEN') return '已冻结'
  return '已驳回'
}

function shortSha(sha: string | null): string {
  return sha === null ? '未登记' : sha.slice(0, 12)
}

function toggleDiffSelection(versionId: string): void {
  const next = new Set(selectedForDiff.value)
  if (next.has(versionId)) {
    next.delete(versionId)
  } else {
    if (next.size >= 2) {
      const [first] = next
      if (first !== undefined) next.delete(first)
    }
    next.add(versionId)
  }
  selectedForDiff.value = next
}

async function executeDiff(): Promise<void> {
  const [from, to] = [...selectedForDiff.value]
  if (from === undefined || to === undefined) return
  diffing.value = true
  diffResult.value = null
  try {
    diffResult.value = await service.diffVersions(from, to)
  } catch {
    error.value = '版本差异对比失败'
  } finally {
    diffing.value = false
  }
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  if (!Number.isFinite(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <section class="records-page">
    <header class="records-heading">
      <div>
        <p class="eyebrow">版本控制 · 不可变快照</p>
        <h2>数据集版本管理</h2>
        <p class="muted">已冻结的版本禁止编辑，作为训练与评测的稳定基线。</p>
      </div>
      <span class="records-count">{{ page?.items.length ?? 0 }} 条当前页版本</span>
    </header>

    <form class="filter-rail" aria-label="数据集版本查询" @submit.prevent="load()">
      <label>
        数据集 ID
        <input v-model="datasetId" maxlength="128" placeholder="dataset-uuid" />
      </label>
      <button type="submit" class="primary-button compact">查询版本</button>
    </form>

    <div
      v-if="selectedForDiff.size === 2"
      class="blind-review-note"
    >
      已选择两个版本进行差异对比
      <button
        type="button"
        class="secondary-button"
        :disabled="diffing"
        style="margin-left: 12px"
        @click="executeDiff"
      >
        {{ diffing ? '对比中…' : '执行对比' }}
      </button>
      <button
        type="button"
        class="text-button"
        style="margin-left: 8px"
        @click="selectedForDiff = new Set()"
      >
        清除选择
      </button>
    </div>

    <p v-if="error !== null" class="panel-error" role="alert">{{ error }}</p>
    <div v-else-if="loading" class="loading-ledger" role="status">正在读取数据集版本…</div>
    <div v-else-if="page?.items.length === 0" class="loading-ledger">该数据集下没有版本记录</div>

    <div
      v-else-if="diffResult !== null"
      class="detail-section"
    >
      <div class="section-heading">
        <h3>版本差异对比</h3>
      </div>
      <dl class="version-grid">
        <dt>基准版本</dt>
        <dd>{{ diffResult.from_version.version }} ({{ shortSha(diffResult.from_version.manifest_sha256) }})</dd>
        <dt>对比版本</dt>
        <dd>{{ diffResult.to_version.version }} ({{ shortSha(diffResult.to_version.manifest_sha256) }})</dd>
        <dt>新增样本</dt>
        <dd>{{ diffResult.added_samples }}</dd>
        <dt>移除样本</dt>
        <dd>{{ diffResult.removed_samples }}</dd>
        <dt>修改样本</dt>
        <dd>{{ diffResult.modified_samples }}</dd>
        <dt>未变样本</dt>
        <dd>{{ diffResult.unchanged_samples }}</dd>
      </dl>
      <ol v-if="diffResult.sample_diff_details.length > 0" class="detection-ledger" style="margin-top: 14px">
        <li
          v-for="item in diffResult.sample_diff_details"
          :key="item.sample_id"
        >
          <div class="detection-row">
            <span class="detection-row__index" aria-hidden="true">
              {{ item.change === 'ADDED' ? '+' : item.change === 'REMOVED' ? '-' : item.change === 'MODIFIED' ? '~' : '=' }}
            </span>
            <span>
              <strong>{{ item.sample_id.slice(0, 8) }}</strong>
              <small>{{ item.change === 'ADDED' ? '新增' : item.change === 'REMOVED' ? '移除' : item.change === 'MODIFIED' ? '修改' : '未变' }}</small>
            </span>
            <span>
              <small>{{ item.diff_summary }}</small>
            </span>
          </div>
        </li>
      </ol>
    </div>

    <ol v-else-if="page !== null" class="detection-ledger">
      <li v-for="item in page.items" :key="item.version_id">
        <button
          type="button"
          class="detection-row"
          :class="{ 'detection-row--selected': selectedForDiff.has(item.version_id) }"
          style="width: 100%; cursor: pointer; text-align: left"
          @click="toggleDiffSelection(item.version_id)"
        >
          <span
            class="detection-row__index"
            aria-hidden="true"
            :style="selectedForDiff.has(item.version_id)
              ? { borderColor: 'var(--accent-deep)', color: 'var(--accent-deep)', background: 'var(--accent-soft)' }
              : {}"
          >
            {{ item.version }}
          </span>
          <span>
            <strong>{{ item.status === 'FROZEN' ? '已冻结' : item.status === 'BUILDING' ? '构建中' : item.status === 'VALIDATING' ? '校验中' : '已驳回' }}</strong>
            <small>样本 {{ item.sample_count }} 条 · {{ formatDate(item.created_at) }}</small>
          </span>
          <span>
            <small style="font-family: var(--font-mono)">SHA {{ shortSha(item.manifest_sha256) }}</small>
          </span>
          <span
            class="state-stamp"
            :data-state="item.status === 'FROZEN' ? 'FINALIZED' : item.status === 'REJECTED' ? 'FAILED' : ''"
          >
            {{ stateLabel(item.status) }}
          </span>
          <span aria-hidden="true">
            {{ selectedForDiff.has(item.version_id) ? '✓' : '○' }}
          </span>
        </button>
      </li>
    </ol>

    <footer v-if="page?.has_more" class="pager">
      <button
        type="button"
        class="secondary-button"
        :disabled="loading || page.next_cursor === null"
        @click="page?.next_cursor && load(page.next_cursor)"
      >
        下一页
      </button>
    </footer>
    <p class="muted" style="margin-top: 14px; font-size: 12px">
      点击两个版本即可对比差异。已冻结版本不得编辑，确保训练基线可复现。
    </p>
  </section>
</template>

<style scoped>
.detection-row--selected {
  border-left-color: var(--accent-deep) !important;
  background: var(--accent-soft) !important;
}
</style>
