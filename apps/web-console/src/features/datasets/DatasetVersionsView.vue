<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/errors'
import type { Uuid } from '@/api/generated'
import type {
  DatasetCatalogSummary,
  DatasetCandidateManifestSummary,
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
const candidateManifests = ref<readonly DatasetCandidateManifestSummary[]>([])
const candidateLoading = ref(false)
const candidateError = ref<string | null>(null)
const candidateManifestId = ref('')
const buildPurpose = ref('')
const building = ref(false)
const buildNotice = ref<string | null>(null)
const approvingCandidateId = ref<string | null>(null)
const approvingVersionId = ref<string | null>(null)
const workflowNotice = ref<string | null>(null)
const selectedForDiff = ref<Set<string>>(new Set())
const diffResult = ref<Awaited<ReturnType<typeof service.diffVersions>> | null>(null)
const diffing = ref(false)

const selectedDataset = computed(() =>
  datasets.value.find((item) => item.dataset_id === datasetId.value) ?? null,
)
const approvedCandidateManifests = computed(() =>
  candidateManifests.value.filter((item) => item.approval_state === 'APPROVED'),
)
const selectedVersion = computed(() => {
  if (selectedForDiff.value.size !== 1) return null
  const [versionId] = selectedForDiff.value
  return page.value?.items.find((item) => item.version_id === versionId) ?? null
})

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
    if (datasetId.value !== '') {
      await Promise.all([load(), loadCandidateManifests()])
    } else {
      page.value = null
      candidateManifests.value = []
    }
  } catch (problem) {
    catalogError.value = problemMessage(problem, '数据集目录暂时无法读取')
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
  } catch (problem) {
    createError.value = problemMessage(problem, '数据集创建失败')
  } finally {
    creating.value = false
  }
}

function selectDataset(): void {
  selectedForDiff.value = new Set()
  diffResult.value = null
  candidateManifestId.value = ''
  buildNotice.value = null
  workflowNotice.value = null
  void load()
  void loadCandidateManifests()
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
  } catch (problem) {
    error.value = problemMessage(problem, '数据集版本列表暂时无法读取')
  } finally {
    loading.value = false
  }
}

async function loadCandidateManifests(): Promise<void> {
  if (datasetId.value === '') {
    candidateManifests.value = []
    return
  }
  candidateLoading.value = true
  candidateError.value = null
  try {
    const manifestPage = await service.listCandidateManifests(
      datasetId.value,
      { pageSize: 100 },
    )
    candidateManifests.value = manifestPage.items
    if (!approvedCandidateManifests.value.some(
      (item) => item.candidate_manifest_id === candidateManifestId.value,
    )) {
      candidateManifestId.value = approvedCandidateManifests.value[0]
        ?.candidate_manifest_id ?? ''
    }
  } catch (problem) {
    candidateError.value = problemMessage(
      problem,
      '候选清单目录暂时无法读取',
    )
  } finally {
    candidateLoading.value = false
  }
}

async function buildVersion(): Promise<void> {
  error.value = null
  buildNotice.value = null
  workflowNotice.value = null
  if (
    datasetId.value === ''
    || candidateManifestId.value === ''
    || buildPurpose.value.trim() === ''
  ) {
    error.value = '请选择已批准候选清单并填写版本用途'
    return
  }
  building.value = true
  try {
    const accepted = await service.createVersion({
      dataset_id: datasetId.value as Uuid,
      candidate_manifest_id: candidateManifestId.value as Uuid,
      purpose: buildPurpose.value.trim(),
    })
    buildPurpose.value = ''
    buildNotice.value = `构建任务已进入队列：${accepted.job_id}`
    await loadCatalog(datasetId.value)
  } catch (problem) {
    error.value = problemMessage(problem, '数据集版本构建任务创建失败')
  } finally {
    building.value = false
  }
}

async function decideCandidateManifest(
  item: DatasetCandidateManifestSummary,
  decision: 'APPROVE' | 'REJECT',
): Promise<void> {
  approvingCandidateId.value = item.candidate_manifest_id
  candidateError.value = null
  workflowNotice.value = null
  try {
    const decided = await service.approveCandidateManifest(
      item.candidate_manifest_id,
      { decision },
    )
    workflowNotice.value = decided.message
    await loadCandidateManifests()
  } catch (problem) {
    candidateError.value = problemMessage(problem, '候选清单审批失败')
  } finally {
    approvingCandidateId.value = null
  }
}

async function decideVersion(
  item: DatasetVersionSummary,
  decision: 'APPROVE' | 'REJECT',
): Promise<void> {
  approvingVersionId.value = item.version_id
  error.value = null
  workflowNotice.value = null
  try {
    const decided = await service.approveVersion(item.version_id, { decision })
    workflowNotice.value = decided.message
    selectedForDiff.value = new Set()
    await loadCatalog(datasetId.value)
  } catch (problem) {
    error.value = problemMessage(problem, '数据集版本审批失败')
  } finally {
    approvingVersionId.value = null
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
  } catch (problem) {
    error.value = problemMessage(problem, '版本差异对比失败')
  } finally {
    diffing.value = false
  }
}

function candidateStateLabel(
  state: DatasetCandidateManifestSummary['approval_state'],
): string {
  if (state === 'REGISTERED') return '待质量审批'
  if (state === 'APPROVED') return '已批准'
  return '已驳回'
}

function problemMessage(problem: unknown, fallback: string): string {
  return problem instanceof ApiError && problem.message.trim() !== ''
    ? problem.message
    : fallback
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
        <p class="muted">完成候选清单审批、版本构建、验证冻结和版本差异审计。</p>
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
              <small>创建目录后，可在下方工作台继续完成候选清单与版本构建。</small>
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

    <section
      v-if="selectedDataset !== null"
      class="resource-directory"
      aria-labelledby="candidate-manifest-title"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">步骤 1 · 质量门禁</p>
          <h3 id="candidate-manifest-title">候选清单</h3>
        </div>
        <button
          type="button"
          class="text-button"
          :disabled="candidateLoading"
          @click="loadCandidateManifests"
        >
          刷新清单
        </button>
      </div>
      <p class="muted">
        清单由受信任的数据构建任务登记；只有独立质量审批通过的不可变对象才能用于版本构建。
      </p>
      <p v-if="candidateError !== null" class="panel-error" role="alert">{{ candidateError }}</p>
      <div v-else-if="candidateLoading" class="loading-ledger" role="status">正在读取候选清单…</div>
      <div v-else-if="candidateManifests.length === 0" class="empty-catalog">
        <strong>暂无候选清单</strong>
        <span>请先运行数据构建任务并登记清单；系统不会用未核验对象绕过质量门禁。</span>
      </div>
      <ol v-else class="detection-ledger candidate-ledger">
        <li v-for="item in candidateManifests" :key="item.candidate_manifest_id">
          <div class="detection-row candidate-row">
            <span class="detection-row__index" aria-hidden="true">CM</span>
            <span>
              <strong>{{ item.manifest_object_key }}</strong>
              <small>{{ item.manifest_bucket }} · {{ item.sample_count }} 个样本</small>
            </span>
            <span>
              <small class="hash-text">SHA {{ shortSha(item.manifest_sha256) }}</small>
              <small>{{ formatDate(item.created_at) }}</small>
            </span>
            <span
              class="state-stamp"
              :data-state="item.approval_state === 'APPROVED' ? 'FINALIZED' : item.approval_state === 'REJECTED' ? 'FAILED' : ''"
            >
              {{ candidateStateLabel(item.approval_state) }}
            </span>
            <span v-if="item.approval_state === 'REGISTERED' && auth.hasPermission('dataset:approve')" class="row-actions">
              <button
                type="button"
                class="secondary-button compact"
                :disabled="approvingCandidateId !== null"
                @click="decideCandidateManifest(item, 'APPROVE')"
              >
                批准
              </button>
              <button
                type="button"
                class="text-button"
                :disabled="approvingCandidateId !== null"
                @click="decideCandidateManifest(item, 'REJECT')"
              >
                驳回
              </button>
            </span>
            <span v-else class="hash-text">{{ item.candidate_manifest_id.slice(0, 12) }}</span>
          </div>
        </li>
      </ol>
    </section>

    <form
      v-if="selectedDataset !== null && auth.hasPermission('dataset:create')"
      class="resource-directory"
      aria-label="创建数据集版本"
      @submit.prevent="buildVersion"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">步骤 2 · 不可变构建</p>
          <h3>创建数据集版本</h3>
        </div>
        <span class="state-stamp">异步执行</span>
      </div>
      <div class="resource-directory__rail resource-directory__rail--wide">
        <label>
          已批准候选清单
          <select
            v-model="candidateManifestId"
            required
            :disabled="candidateLoading || approvedCandidateManifests.length === 0"
          >
            <option value="" disabled>
              {{ approvedCandidateManifests.length === 0 ? '暂无可用清单' : '请选择候选清单' }}
            </option>
            <option
              v-for="item in approvedCandidateManifests"
              :key="item.candidate_manifest_id"
              :value="item.candidate_manifest_id"
            >
              {{ item.manifest_object_key }} · {{ item.sample_count }} 个样本 · SHA {{ shortSha(item.manifest_sha256) }}
            </option>
          </select>
        </label>
        <label>
          版本用途
          <input
            v-model="buildPurpose"
            required
            maxlength="256"
            placeholder="例如：2026 年 8 月受控增量训练"
          />
        </label>
        <button
          type="submit"
          class="primary-button compact"
          :disabled="building || approvedCandidateManifests.length === 0"
        >
          {{ building ? '提交中…' : '创建构建任务' }}
        </button>
      </div>
      <p v-if="approvedCandidateManifests.length === 0 && !candidateLoading" class="decision-caveat">
        当前没有已批准候选清单。质量负责人批准清单后，构建入口会自动可用。
      </p>
      <p v-if="buildNotice !== null" class="panel-notice" role="status">
        {{ buildNotice }}
      </p>
    </form>

    <p v-if="workflowNotice !== null" class="panel-notice" role="status">
      {{ workflowNotice }}
    </p>

    <div
      v-if="selectedVersion?.status === 'VALIDATING' && auth.hasPermission('dataset:approve')"
      class="blind-review-note validation-approval"
    >
      <span>
        步骤 3 · 版本 v{{ selectedVersion.version }} 已完成构建校验，请提交冻结或驳回结论。
      </span>
      <span class="row-actions">
        <button
          type="button"
          class="secondary-button"
          :disabled="approvingVersionId !== null"
          @click="decideVersion(selectedVersion, 'APPROVE')"
        >
          冻结版本
        </button>
        <button
          type="button"
          class="text-button"
          :disabled="approvingVersionId !== null"
          @click="decideVersion(selectedVersion, 'REJECT')"
        >
          驳回版本
        </button>
      </span>
    </div>

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

.candidate-ledger {
  margin-top: 16px;
}

.candidate-row {
  cursor: default;
}

.row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.validation-approval {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

@media (max-width: 760px) {
  .validation-approval {
    align-items: stretch;
    flex-direction: column;
  }

  .row-actions {
    justify-content: flex-start;
  }
}
</style>
