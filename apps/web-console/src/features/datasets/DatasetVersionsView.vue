<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type {
  DatasetCatalogSummary,
  DatasetVersionPage,
  DatasetVersionSummary,
} from './service'
import { DatasetService } from './service'
import { useApplicationApiClient } from '@/api/runtime'
import { useAuthStore } from '@/stores/auth'

const service = new DatasetService(useApplicationApiClient())
const auth = useAuthStore()
const page = ref<DatasetVersionPage | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const datasetId = ref('')
const datasets = ref<readonly DatasetCatalogSummary[]>([])
const catalogLoading = ref(false)
const catalogError = ref<string | null>(null)
const datasetName = ref('')
const datasetPurpose = ref('')
const creating = ref(false)
const createError = ref<string | null>(null)
const createNotice = ref<string | null>(null)
const selectedForDiff = ref<Set<string>>(new Set())
const diffResult = ref<Awaited<ReturnType<typeof service.diffVersions>> | null>(null)
const diffing = ref(false)

const selectedDataset = computed(() =>
  datasets.value.find((item) => item.dataset_id === datasetId.value) ?? null,
)

onMounted(() => void loadCatalog())

async function loadCatalog(preferredId?: string): Promise<void> {
  catalogLoading.value = true
  catalogError.value = null
  try {
    const catalog = await service.listDatasets({ pageSize: 200 })
    datasets.value = catalog.items
    const nextId = preferredId
      ?? (datasets.value.some((item) => item.dataset_id === datasetId.value)
        ? datasetId.value
        : datasets.value[0]?.dataset_id)
    datasetId.value = nextId ?? ''
    if (datasetId.value !== '') await load()
    else page.value = null
  } catch {
    catalogError.value = '数据集目录暂时无法读取'
  } finally {
    catalogLoading.value = false
  }
}

async function createDataset(): Promise<void> {
  createError.value = null
  createNotice.value = null
  if (datasetName.value.trim() === '' || datasetPurpose.value.trim() === '') {
    createError.value = '数据集名称和用途均不能为空'
    return
  }
  creating.value = true
  try {
    const created = await service.createDataset({
      dataset_name: datasetName.value.trim(),
      purpose: datasetPurpose.value.trim(),
    })
    datasetName.value = ''
    datasetPurpose.value = ''
    createNotice.value = `已创建数据集 ${created.dataset_name}`
    await loadCatalog(created.dataset_id)
  } catch {
    createError.value = '数据集创建失败；请确认名称未被占用'
  } finally {
    creating.value = false
  }
}

function selectDataset(): void {
  selectedForDiff.value = new Set()
  diffResult.value = null
  void load()
}

async function load(cursor?: string): Promise<void> {
  if (datasetId.value.trim() === '') {
    page.value = null
    error.value = null
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
        <p class="muted">从目录选择数据集后查看不可变版本；无需再手工查找 UUID。</p>
      </div>
      <span class="records-count">{{ datasets.length }} 个数据集 · {{ page?.items.length ?? 0 }} 个版本</span>
    </header>

    <section class="resource-directory" aria-labelledby="dataset-directory-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">资源目录</p>
          <h3 id="dataset-directory-title">选择数据集</h3>
        </div>
        <button
          type="button"
          class="text-button"
          :disabled="catalogLoading"
          @click="loadCatalog()"
        >
          刷新目录
        </button>
      </div>

      <p v-if="catalogError !== null" class="panel-error" role="alert">{{ catalogError }}</p>
      <div v-else-if="catalogLoading" class="loading-ledger" role="status">正在读取数据集目录…</div>
      <template v-else>
        <div class="resource-directory__rail">
          <label>
            数据集
            <select v-model="datasetId" :disabled="datasets.length === 0" @change="selectDataset">
              <option value="" disabled>{{ datasets.length === 0 ? '暂无数据集' : '请选择数据集' }}</option>
              <option v-for="item in datasets" :key="item.dataset_id" :value="item.dataset_id">
                {{ item.dataset_name }} · {{ item.version_count }} 个版本
              </option>
            </select>
          </label>
          <div v-if="selectedDataset !== null" class="resource-identity">
            <span>数据集 ID</span>
            <strong class="hash-text">{{ selectedDataset.dataset_id }}</strong>
            <small>{{ selectedDataset.purpose }} · 创建于 {{ formatDate(selectedDataset.created_at) }}</small>
          </div>
          <div v-else class="empty-catalog">
            <strong>目录为空</strong>
            <span>先创建数据集，系统会生成可用于版本构建的 UUID。</span>
          </div>
        </div>

        <form
          v-if="auth.hasPermission('dataset:create')"
          class="catalog-create-form"
          aria-label="新建数据集"
          @submit.prevent="createDataset"
        >
          <div>
            <span class="catalog-create-form__index">＋</span>
            <div>
              <strong>新建数据集</strong>
              <small>只创建目录项；版本仍需绑定已批准候选清单。</small>
            </div>
          </div>
          <label>名称<input v-model="datasetName" maxlength="128" required placeholder="例如：刀具缺陷生产候选集" /></label>
          <label>用途<input v-model="datasetPurpose" maxlength="128" required placeholder="例如：受控增量训练" /></label>
          <button type="submit" class="primary-button compact" :disabled="creating">
            {{ creating ? '创建中…' : '创建数据集' }}
          </button>
        </form>
        <p v-if="createError !== null" class="panel-error" role="alert">{{ createError }}</p>
        <p v-if="createNotice !== null" class="panel-notice" role="status">{{ createNotice }}</p>
      </template>
    </section>

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
