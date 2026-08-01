<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
const activeStep = ref<1 | 2 | 3 | 4>(1)
let progressPoller: number | null = null

const selectedDataset = computed(() =>
  datasets.value.find((item) => item.dataset_id === datasetId.value) ?? null,
)
const approvedCandidateManifests = computed(() =>
  candidateManifests.value.filter((item) => item.approval_state === 'APPROVED'),
)
const selectedCandidateManifest = computed(() =>
  approvedCandidateManifests.value.find(
    (item) => item.candidate_manifest_id === candidateManifestId.value,
  ) ?? null,
)
const workflowVersion = computed(() => {
  const versions = page.value?.items ?? []
  return versions.find((item) => item.status === 'VALIDATING')
    ?? versions.find((item) => item.status === 'BUILDING')
    ?? versions[0]
    ?? null
})
const pendingCandidateCount = computed(() =>
  candidateManifests.value.filter((item) => item.approval_state === 'REGISTERED').length,
)
const wizardSteps = computed(() => [
  {
    number: 1 as const,
    title: '选择目录',
    detail: selectedDataset.value?.dataset_name ?? '选择或创建数据集',
    state: selectedDataset.value === null ? 'current' : 'done',
  },
  {
    number: 2 as const,
    title: '确认数据',
    detail: selectedCandidateManifest.value === null
      ? pendingCandidateCount.value > 0
        ? `${pendingCandidateCount.value} 份清单待审批`
        : '等待可用清单'
      : `${selectedCandidateManifest.value.sample_count} 个样本已就绪`,
    state: selectedCandidateManifest.value === null ? 'waiting' : 'done',
  },
  {
    number: 3 as const,
    title: '发起构建',
    detail: workflowVersion.value === null
      ? '填写用途并提交'
      : `版本 v${workflowVersion.value.version}`,
    state: workflowVersion.value === null ? 'waiting' : 'done',
  },
  {
    number: 4 as const,
    title: '验证冻结',
    detail: workflowVersion.value === null
      ? '等待构建'
      : stateLabel(workflowVersion.value.status),
    state: workflowVersion.value?.status === 'FROZEN'
      ? 'done'
      : workflowVersion.value?.status === 'REJECTED'
        ? 'failed'
        : 'waiting',
  },
])

onMounted(() => void loadCatalog())
onBeforeUnmount(stopProgressPolling)

watch(
  () => [activeStep.value, workflowVersion.value?.status] as const,
  ([step, status]) => {
    stopProgressPolling()
    if (step === 4 && status === 'BUILDING') {
      progressPoller = window.setInterval(() => {
        if (!loading.value) void load()
      }, 4000)
    }
  },
)

function stopProgressPolling(): void {
  if (progressPoller !== null) {
    window.clearInterval(progressPoller)
    progressPoller = null
  }
}

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
      syncWizardStep()
    } else {
      page.value = null
      candidateManifests.value = []
      activeStep.value = 1
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
  activeStep.value = datasetId.value === '' ? 1 : 2
  void Promise.all([load(), loadCandidateManifests()]).then(syncWizardStep)
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
    activeStep.value = 4
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
    if (decision === 'APPROVE') activeStep.value = 3
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
    activeStep.value = decision === 'APPROVE' ? 4 : 3
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

function openWizardStep(step: 1 | 2 | 3 | 4): void {
  if (canOpenWizardStep(step)) activeStep.value = step
}

function canOpenWizardStep(step: 1 | 2 | 3 | 4): boolean {
  if (step === 1) return true
  if (step === 2) return selectedDataset.value !== null
  if (step === 3) return selectedCandidateManifest.value !== null
  return workflowVersion.value !== null
}

function startAnotherVersion(): void {
  buildNotice.value = null
  workflowNotice.value = null
  activeStep.value = selectedCandidateManifest.value === null ? 2 : 3
}

function syncWizardStep(): void {
  if (selectedDataset.value === null) {
    activeStep.value = 1
    return
  }
  if (pendingCandidateCount.value > 0 || selectedCandidateManifest.value === null) {
    activeStep.value = 2
    return
  }
  activeStep.value = workflowVersion.value === null ? 3 : 4
}

function buildPhaseState(phase: number): 'done' | 'active' | 'waiting' | 'failed' {
  const status = workflowVersion.value?.status
  if (status === undefined) return phase === 1 ? 'active' : 'waiting'
  if (status === 'REJECTED') return phase === 4 ? 'failed' : 'done'
  const current = status === 'BUILDING' ? 2 : status === 'VALIDATING' ? 3 : 4
  if (phase < current) return 'done'
  if (phase === current) return status === 'FROZEN' ? 'done' : 'active'
  return 'waiting'
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
  <section class="records-page dataset-builder">
    <header class="records-heading builder-heading">
      <div>
        <p class="eyebrow">可视化构建向导 · 不可变快照</p>
        <h2>数据集版本管理</h2>
        <p class="muted">跟随系统推荐的下一步，完成数据确认、构建校验和版本冻结。</p>
      </div>
      <div class="builder-heading__aside">
        <span class="live-mark"><i aria-hidden="true"></i>流程在线</span>
        <span class="records-count">{{ datasets.length }} 个数据集 · {{ page?.items.length ?? 0 }} 个版本</span>
      </div>
    </header>

    <div class="builder-board">
      <nav class="workflow-map" aria-label="数据集构建步骤">
        <button
          v-for="step in wizardSteps"
          :key="step.number"
          type="button"
          class="workflow-node"
          :class="{ 'workflow-node--active': activeStep === step.number }"
          :data-state="step.state"
          :disabled="!canOpenWizardStep(step.number)"
          :aria-current="activeStep === step.number ? 'step' : undefined"
          @click="openWizardStep(step.number)"
        >
          <span class="workflow-node__number">{{ String(step.number).padStart(2, '0') }}</span>
          <span>
            <strong>{{ step.title }}</strong>
            <small>{{ step.detail }}</small>
          </span>
          <span class="workflow-node__signal" aria-hidden="true">
            {{ step.state === 'done' ? '✓' : step.state === 'failed' ? '!' : '→' }}
          </span>
        </button>
      </nav>

      <section class="wizard-stage" :aria-labelledby="`wizard-step-${activeStep}`">
        <header class="wizard-stage__header">
          <div>
            <span>步骤 {{ activeStep }} / 4</span>
            <h3 :id="`wizard-step-${activeStep}`">{{ wizardSteps[activeStep - 1]?.title }}</h3>
          </div>
          <button
            type="button"
            class="text-button"
            :disabled="catalogLoading || loading || candidateLoading"
            @click="loadCatalog(datasetId || undefined)"
          >
            刷新当前状态
          </button>
        </header>

        <p v-if="catalogError !== null" class="panel-error" role="alert">{{ catalogError }}</p>
        <p v-if="candidateError !== null" class="panel-error" role="alert">{{ candidateError }}</p>
        <p v-if="error !== null" class="panel-error" role="alert">{{ error }}</p>
        <p v-if="workflowNotice !== null" class="panel-notice" role="status">{{ workflowNotice }}</p>
        <p v-if="createNotice !== null" class="panel-notice" role="status">{{ createNotice }}</p>

        <Transition name="wizard" mode="out-in">
          <div v-if="activeStep === 1" key="directory" class="wizard-pane">
            <div class="pane-intro">
              <span class="pane-intro__glyph" aria-hidden="true">01</span>
              <div>
                <h4>先确定版本归属</h4>
                <p>选择已有目录，或在这里新建一个。后续清单和版本都会自动归入该数据集。</p>
              </div>
            </div>

            <div v-if="catalogLoading" class="loading-ledger" role="status">正在读取数据集目录…</div>
            <template v-else>
              <label class="hero-field">
                <span>目标数据集</span>
                <select v-model="datasetId" :disabled="datasets.length === 0" @change="selectDataset">
                  <option value="" disabled>{{ datasets.length === 0 ? '暂无数据集，请在下方创建' : '请选择数据集' }}</option>
                  <option v-for="item in datasets" :key="item.dataset_id" :value="item.dataset_id">
                    {{ item.dataset_name }} · {{ item.version_count }} 个版本
                  </option>
                </select>
              </label>

              <div v-if="selectedDataset !== null" class="selection-ticket">
                <span class="selection-ticket__check" aria-hidden="true">✓</span>
                <div>
                  <strong>{{ selectedDataset.dataset_name }}</strong>
                  <small>{{ selectedDataset.purpose }}</small>
                </div>
                <code>{{ selectedDataset.dataset_id }}</code>
                <button type="button" class="primary-button" @click="activeStep = 2">继续确认数据</button>
              </div>

              <form
                v-if="auth.hasPermission('dataset:create')"
                class="quick-create"
                aria-label="新建数据集"
                @submit.prevent="createDataset"
              >
                <div class="quick-create__title">
                  <span>＋</span>
                  <div><strong>没有合适的目录？</strong><small>直接创建，不会离开当前向导</small></div>
                </div>
                <label>名称<input v-model="datasetName" maxlength="128" required placeholder="例如：刀具缺陷生产候选集" /></label>
                <label>用途<input v-model="datasetPurpose" maxlength="128" required placeholder="例如：受控增量训练" /></label>
                <button type="submit" class="secondary-button" :disabled="creating">
                  {{ creating ? '创建中…' : '创建并继续' }}
                </button>
              </form>
              <p v-if="createError !== null" class="panel-error" role="alert">{{ createError }}</p>
            </template>
          </div>

          <div v-else-if="activeStep === 2" key="manifest" class="wizard-pane">
            <div class="pane-intro">
              <span class="pane-intro__glyph" aria-hidden="true">02</span>
              <div>
                <h4>选择通过质量门禁的数据</h4>
                <p>卡片展示样本量、对象位置和校验摘要；绿色清单可以直接用于构建。</p>
              </div>
              <div class="pane-metrics" aria-label="候选清单概况">
                <span><strong>{{ candidateManifests.length }}</strong>全部</span>
                <span><strong>{{ approvedCandidateManifests.length }}</strong>可用</span>
                <span><strong>{{ pendingCandidateCount }}</strong>待审</span>
              </div>
            </div>

            <div v-if="candidateLoading" class="loading-ledger" role="status">正在读取候选清单…</div>
            <div v-else-if="candidateManifests.length === 0" class="visual-empty">
              <span class="visual-empty__mark" aria-hidden="true">⌁</span>
              <div>
                <strong>构建服务尚未登记候选清单</strong>
                <p>原始样本需要先由受信任的数据构建任务生成清单。登记完成后，这里会自动出现可审批卡片。</p>
              </div>
              <button type="button" class="secondary-button" @click="loadCandidateManifests">重新检查</button>
            </div>
            <div v-else class="manifest-gallery">
              <article
                v-for="item in candidateManifests"
                :key="item.candidate_manifest_id"
                class="manifest-card"
                :class="{ 'manifest-card--selected': item.candidate_manifest_id === candidateManifestId }"
                :data-state="item.approval_state"
              >
                <button
                  type="button"
                  class="manifest-card__main"
                  :disabled="item.approval_state !== 'APPROVED'"
                  @click="candidateManifestId = item.candidate_manifest_id"
                >
                  <span class="manifest-card__status">{{ candidateStateLabel(item.approval_state) }}</span>
                  <strong>{{ item.sample_count.toLocaleString('zh-CN') }}</strong>
                  <small>个有效样本</small>
                  <span class="manifest-card__path">{{ item.manifest_object_key }}</span>
                  <code>SHA {{ shortSha(item.manifest_sha256) }}</code>
                </button>
                <div class="manifest-card__footer">
                  <span>{{ formatDate(item.created_at) }}</span>
                  <span v-if="item.candidate_manifest_id === candidateManifestId" class="chosen-mark">已选择 ✓</span>
                  <span v-else-if="item.approval_state === 'REGISTERED' && auth.hasPermission('dataset:approve')" class="row-actions">
                    <button type="button" class="secondary-button compact" :disabled="approvingCandidateId !== null" @click="decideCandidateManifest(item, 'APPROVE')">批准</button>
                    <button type="button" class="text-button" :disabled="approvingCandidateId !== null" @click="decideCandidateManifest(item, 'REJECT')">驳回</button>
                  </span>
                </div>
              </article>
            </div>

            <div class="wizard-actions">
              <button type="button" class="text-button" @click="activeStep = 1">返回目录</button>
              <span v-if="selectedCandidateManifest === null">请选择一份绿色的已批准清单</span>
              <button type="button" class="primary-button" :disabled="selectedCandidateManifest === null" @click="activeStep = 3">使用这份数据</button>
            </div>
          </div>

          <form v-else-if="activeStep === 3" key="build" class="wizard-pane" @submit.prevent="buildVersion">
            <div class="pane-intro">
              <span class="pane-intro__glyph" aria-hidden="true">03</span>
              <div>
                <h4>检查摘要并发起构建</h4>
                <p>只需补充版本用途，其余对象地址、哈希和样本数由系统带入。</p>
              </div>
            </div>

            <div v-if="selectedCandidateManifest !== null" class="build-blueprint">
              <div class="blueprint-source">
                <span>输入清单</span>
                <strong>{{ selectedCandidateManifest.sample_count }} 个样本</strong>
                <code>{{ selectedCandidateManifest.manifest_object_key }}</code>
              </div>
              <span class="blueprint-arrow" aria-hidden="true">⟶</span>
              <div class="blueprint-process">
                <span>受控处理</span>
                <strong>校验 · 固化 · 追溯</strong>
                <small>异步任务自动执行</small>
              </div>
              <span class="blueprint-arrow" aria-hidden="true">⟶</span>
              <div class="blueprint-output">
                <span>目标</span>
                <strong>{{ selectedDataset?.dataset_name }}</strong>
                <small>新不可变版本</small>
              </div>
            </div>

            <label class="hero-field">
              <span>这个版本将用于什么？</span>
              <input v-model="buildPurpose" required maxlength="256" placeholder="例如：2026 年 8 月受控增量训练" />
              <small>用途会进入审计记录，建议写清时间、场景或训练目标。</small>
            </label>

            <div class="wizard-actions">
              <button type="button" class="text-button" @click="activeStep = 2">返回选择数据</button>
              <span>提交后可离开页面，构建任务会在后台继续。</span>
              <button type="submit" class="primary-button launch-button" :disabled="building || !auth.hasPermission('dataset:create')">
                {{ building ? '正在启动…' : '启动版本构建' }} <b aria-hidden="true">→</b>
              </button>
            </div>
          </form>

          <div v-else key="validation" class="wizard-pane">
            <div class="pane-intro">
              <span class="pane-intro__glyph" aria-hidden="true">04</span>
              <div>
                <h4>{{ workflowVersion?.status === 'FROZEN' ? '版本已可用于训练' : '跟踪构建与验证' }}</h4>
                <p>{{ workflowVersion === null ? '还没有构建任务。返回上一步创建一个新版本。' : `版本 v${workflowVersion.version} · ${stateLabel(workflowVersion.status)}` }}</p>
              </div>
              <span v-if="workflowVersion !== null" class="version-beacon" :data-state="workflowVersion.status">v{{ workflowVersion.version }}</span>
            </div>

            <ol class="build-track" aria-label="构建进度">
              <li v-for="(label, index) in ['任务登记', '对象构建', '完整性校验', '版本冻结']" :key="label" :data-state="buildPhaseState(index + 1)">
                <span>{{ buildPhaseState(index + 1) === 'done' ? '✓' : index + 1 }}</span>
                <strong>{{ label }}</strong>
                <small>{{ index === 0 ? '请求已追踪' : index === 1 ? '生成不可变对象' : index === 2 ? '核验样本与哈希' : '批准为训练基线' }}</small>
              </li>
            </ol>

            <p v-if="buildNotice !== null" class="panel-notice" role="status">{{ buildNotice }}</p>

            <div v-if="workflowVersion?.status === 'BUILDING'" class="action-callout action-callout--working">
              <span class="radar" aria-hidden="true"><i></i></span>
              <div><strong>构建服务正在处理 · 自动更新中</strong><p>页面每 4 秒同步一次状态；离开页面不会中断后台任务。</p></div>
              <button type="button" class="secondary-button" :disabled="loading" @click="loadCatalog(datasetId)">刷新进度</button>
            </div>

            <div v-else-if="workflowVersion?.status === 'VALIDATING'" class="action-callout action-callout--review">
              <span class="action-callout__icon" aria-hidden="true">✓</span>
              <div><strong>自动校验已完成，等待最终确认</strong><p>冻结后版本不可修改，并可作为训练任务的数据基线。</p></div>
              <span v-if="auth.hasPermission('dataset:approve')" class="row-actions">
                <button type="button" class="primary-button" :disabled="approvingVersionId !== null" @click="decideVersion(workflowVersion, 'APPROVE')">冻结并完成</button>
                <button type="button" class="text-button" :disabled="approvingVersionId !== null" @click="decideVersion(workflowVersion, 'REJECT')">驳回</button>
              </span>
            </div>

            <div v-else-if="workflowVersion?.status === 'FROZEN'" class="action-callout action-callout--success">
              <span class="action-callout__icon" aria-hidden="true">✓</span>
              <div><strong>数据集版本 v{{ workflowVersion.version }} 已冻结</strong><p>{{ workflowVersion.sample_count }} 个样本已形成可复现训练基线，哈希 {{ shortSha(workflowVersion.manifest_sha256) }}。</p></div>
              <button type="button" class="secondary-button" @click="startAnotherVersion">构建新版本</button>
            </div>

            <div v-else-if="workflowVersion?.status === 'REJECTED'" class="action-callout action-callout--failed">
              <span class="action-callout__icon" aria-hidden="true">!</span>
              <div><strong>本次版本未通过</strong><p>失败不会生成可训练版本。请重新选择数据或修正上游清单后再构建。</p></div>
              <button type="button" class="secondary-button" @click="startAnotherVersion">重新构建</button>
            </div>

            <div v-else-if="workflowVersion === null" class="visual-empty">
              <span class="visual-empty__mark" aria-hidden="true">04</span>
              <div><strong>等待第一个构建任务</strong><p>前两步已经准备好时，返回“发起构建”即可。</p></div>
              <button type="button" class="primary-button" @click="activeStep = 3">返回发起构建</button>
            </div>
          </div>
        </Transition>
      </section>
    </div>

    <details class="advanced-ledger">
      <summary>
        <span><strong>高级记录与版本对比</strong><small>查看完整版本台账、对象哈希和差异明细</small></span>
        <span>{{ page?.items.length ?? 0 }} 条记录 ＋</span>
      </summary>
      <div class="advanced-ledger__body">
        <div v-if="selectedDataset !== null" class="dataset-signature">
          <span>当前数据集</span><strong>{{ selectedDataset.dataset_name }}</strong><code>{{ selectedDataset.dataset_id }}</code>
        </div>

        <div v-if="selectedForDiff.size === 2" class="blind-review-note">
          已选择两个版本进行差异对比
          <button type="button" class="secondary-button compact" :disabled="diffing" @click="executeDiff">{{ diffing ? '对比中…' : '执行对比' }}</button>
          <button type="button" class="text-button" @click="selectedForDiff = new Set()">清除选择</button>
        </div>

        <div v-if="loading" class="loading-ledger" role="status">正在读取数据集版本…</div>
        <div v-else-if="page?.items.length === 0" class="loading-ledger">该数据集下没有版本记录</div>

        <div v-else-if="diffResult !== null" class="detail-section">
          <div class="section-heading"><h3>版本差异对比</h3><button type="button" class="text-button" @click="diffResult = null">返回台账</button></div>
          <dl class="version-grid">
            <dt>基准版本</dt><dd>{{ diffResult.from_version.version }} ({{ shortSha(diffResult.from_version.manifest_sha256) }})</dd>
            <dt>对比版本</dt><dd>{{ diffResult.to_version.version }} ({{ shortSha(diffResult.to_version.manifest_sha256) }})</dd>
            <dt>新增样本</dt><dd>{{ diffResult.added_samples }}</dd>
            <dt>移除样本</dt><dd>{{ diffResult.removed_samples }}</dd>
            <dt>修改样本</dt><dd>{{ diffResult.modified_samples }}</dd>
            <dt>未变样本</dt><dd>{{ diffResult.unchanged_samples }}</dd>
          </dl>
        </div>

        <ol v-else-if="page !== null" class="detection-ledger version-ledger">
          <li v-for="item in page.items" :key="item.version_id">
            <button type="button" class="detection-row" :class="{ 'detection-row--selected': selectedForDiff.has(item.version_id) }" @click="toggleDiffSelection(item.version_id)">
              <span class="detection-row__index" aria-hidden="true">{{ item.version }}</span>
              <span><strong>{{ stateLabel(item.status) }}</strong><small>样本 {{ item.sample_count }} 条 · {{ formatDate(item.created_at) }}</small></span>
              <span><small class="hash-text">SHA {{ shortSha(item.manifest_sha256) }}</small></span>
              <span class="state-stamp" :data-state="item.status === 'FROZEN' ? 'FINALIZED' : item.status === 'REJECTED' ? 'FAILED' : ''">{{ stateLabel(item.status) }}</span>
              <span aria-hidden="true">{{ selectedForDiff.has(item.version_id) ? '✓' : '○' }}</span>
            </button>
          </li>
        </ol>

        <footer v-if="page?.has_more" class="pager">
          <button type="button" class="secondary-button" :disabled="loading || page.next_cursor === null" @click="page?.next_cursor && load(page.next_cursor)">下一页</button>
        </footer>
        <p class="muted advanced-hint">点击两个版本即可对比差异。已冻结版本不得编辑，确保训练基线可复现。</p>
      </div>
    </details>
  </section>
</template>

<style scoped>
.dataset-builder {
  --builder-navy: #073b5c;
  --builder-deep: #042b45;
  --builder-mint: #27c79a;
  --builder-paper: #fbfdff;
}

.builder-heading__aside,
.row-actions,
.wizard-actions,
.selection-ticket,
.pane-intro,
.action-callout,
.dataset-signature {
  display: flex;
  align-items: center;
}

.builder-heading__aside {
  gap: 10px;
}

.live-mark {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  color: #17795e;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.live-mark i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--builder-mint);
  box-shadow: 0 0 0 4px rgb(39 199 154 / 13%);
  animation: builder-pulse 2.2s ease-in-out infinite;
}

.builder-board {
  display: grid;
  grid-template-columns: 282px minmax(0, 1fr);
  min-height: 570px;
  overflow: hidden;
  border: 1px solid #c8d9e5;
  border-radius: 8px;
  background: var(--builder-paper);
  box-shadow: 0 14px 38px rgb(20 59 86 / 9%);
}

.workflow-map {
  position: relative;
  display: grid;
  align-content: start;
  gap: 0;
  padding: 28px 18px;
  overflow: hidden;
  background:
    linear-gradient(90deg, rgb(93 201 210 / 5%) 1px, transparent 1px),
    linear-gradient(rgb(93 201 210 / 5%) 1px, transparent 1px),
    linear-gradient(155deg, var(--builder-navy), var(--builder-deep));
  background-size: 22px 22px, 22px 22px, auto;
}

.workflow-map::after {
  position: absolute;
  right: -70px;
  bottom: -90px;
  width: 210px;
  height: 210px;
  border: 1px solid rgb(84 218 207 / 14%);
  border-radius: 50%;
  box-shadow: 0 0 0 28px rgb(84 218 207 / 4%), 0 0 0 62px rgb(84 218 207 / 3%);
  content: "";
}

.workflow-node {
  position: relative;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) 20px;
  gap: 11px;
  align-items: center;
  min-height: 86px;
  padding: 13px 12px;
  border: 0;
  color: rgb(222 239 248 / 67%);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: color 180ms ease, background 180ms ease, transform 180ms ease;
}

.workflow-node:not(:last-child)::after {
  position: absolute;
  z-index: 0;
  top: 63px;
  bottom: -23px;
  left: 30px;
  width: 1px;
  background: rgb(159 213 227 / 23%);
  content: "";
}

.workflow-node:hover:not(:disabled),
.workflow-node--active {
  color: #fff;
  background: rgb(255 255 255 / 7%);
  transform: translateX(3px);
}

.workflow-node--active {
  box-shadow: inset 3px 0 var(--builder-mint);
}

.workflow-node:disabled {
  cursor: not-allowed;
  opacity: 0.47;
}

.workflow-node__number {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 1px solid rgb(187 224 236 / 35%);
  border-radius: 50%;
  color: #c8e7f1;
  background: #0b4568;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 800;
}

.workflow-node[data-state="done"] .workflow-node__number {
  border-color: rgb(39 199 154 / 60%);
  color: #b9f8e4;
  background: rgb(22 133 104 / 44%);
}

.workflow-node > span:nth-child(2) {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.workflow-node strong {
  font-size: 13px;
  letter-spacing: 0.04em;
}

.workflow-node small {
  overflow: hidden;
  opacity: 0.75;
  font-size: 10.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-node__signal {
  color: var(--builder-mint);
  font-family: var(--font-mono);
  font-weight: 900;
}

.wizard-stage {
  position: relative;
  min-width: 0;
  padding: 26px 30px 30px;
  background:
    linear-gradient(135deg, rgb(20 121 172 / 3%) 25%, transparent 25%) 0 0 / 18px 18px,
    var(--builder-paper);
}

.wizard-stage__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 22px;
  padding-bottom: 15px;
  border-bottom: 1px solid #dce7ee;
}

.wizard-stage__header > div {
  display: flex;
  gap: 12px;
  align-items: baseline;
}

.wizard-stage__header span {
  color: var(--accent-ink);
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 0.1em;
}

.wizard-stage__header h3 {
  margin: 0;
  color: var(--builder-deep);
  font-size: 18px;
}

.wizard-pane {
  display: grid;
  gap: 20px;
}

.pane-intro {
  gap: 15px;
  min-height: 62px;
}

.pane-intro__glyph {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 52px;
  height: 52px;
  border: 1px solid #b9d5e4;
  border-radius: 16px 3px 16px 3px;
  color: var(--accent-ink);
  background: #eef8fc;
  font-family: var(--font-mono);
  font-size: 15px;
  font-weight: 900;
}

.pane-intro h4 {
  margin: 0 0 5px;
  color: var(--builder-deep);
  font-size: 17px;
}

.pane-intro p,
.visual-empty p,
.action-callout p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.65;
}

.pane-metrics {
  display: flex;
  gap: 1px;
  margin-left: auto;
  overflow: hidden;
  border: 1px solid #d9e5ec;
  border-radius: 4px;
  background: #d9e5ec;
}

.pane-metrics span {
  display: grid;
  min-width: 68px;
  padding: 7px 10px;
  color: var(--muted);
  background: #fff;
  font-size: 9.5px;
  text-align: center;
}

.pane-metrics strong {
  color: var(--builder-navy);
  font-family: var(--font-mono);
  font-size: 16px;
}

.hero-field {
  display: grid;
  gap: 8px;
  max-width: 760px;
}

.hero-field > span,
.quick-create label {
  color: var(--builder-navy);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.07em;
}

.hero-field select,
.hero-field input,
.quick-create input {
  width: 100%;
  min-height: 48px;
  padding: 10px 13px;
  border: 1px solid #b9ccda;
  border-radius: 4px;
  color: var(--ink);
  background: #fff;
  box-shadow: inset 0 1px 2px rgb(25 67 94 / 4%);
  font-size: 13px;
}

.hero-field select:focus,
.hero-field input:focus,
.quick-create input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgb(39 156 241 / 12%);
  outline: none;
}

.hero-field > small {
  color: var(--muted);
  font-size: 10.5px;
}

.selection-ticket {
  gap: 13px;
  padding: 13px 15px;
  border: 1px solid #b9e4d6;
  border-left: 4px solid var(--builder-mint);
  border-radius: 4px;
  background: #f0fbf7;
}

.selection-ticket__check,
.action-callout__icon {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  color: #fff;
  background: #1aa37b;
  font-weight: 900;
}

.selection-ticket > div {
  display: grid;
  gap: 3px;
}

.selection-ticket small {
  color: var(--muted);
  font-size: 11px;
}

.selection-ticket code,
.dataset-signature code {
  min-width: 0;
  margin-left: auto;
  overflow: hidden;
  color: #568073;
  font-family: var(--font-mono);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quick-create {
  display: grid;
  grid-template-columns: minmax(190px, 1fr) minmax(160px, 1fr) minmax(180px, 1.2fr) auto;
  gap: 12px;
  align-items: end;
  padding: 17px;
  border: 1px dashed #b9ccda;
  border-radius: 5px;
  background: rgb(239 246 250 / 60%);
}

.quick-create label {
  display: grid;
  gap: 6px;
}

.quick-create input {
  min-height: 40px;
}

.quick-create__title {
  display: flex;
  gap: 10px;
  align-items: center;
  min-height: 40px;
}

.quick-create__title > span {
  color: var(--accent-deep);
  font-size: 25px;
  font-weight: 300;
}

.quick-create__title div {
  display: grid;
  gap: 3px;
}

.quick-create__title small {
  color: var(--muted);
  font-size: 10px;
}

.visual-empty {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
  min-height: 120px;
  padding: 22px;
  border: 1px dashed #aec9d9;
  border-radius: 5px;
  background: #f5fafc;
}

.visual-empty__mark {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border: 1px solid #c7dae5;
  border-radius: 50%;
  color: #6c9bb5;
  font-family: var(--font-mono);
  font-size: 18px;
}

.visual-empty strong {
  display: block;
  margin-bottom: 6px;
  color: var(--builder-navy);
}

.manifest-gallery {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.manifest-card {
  min-width: 0;
  overflow: hidden;
  border: 1px solid #d2dfe7;
  border-radius: 5px;
  background: #fff;
  box-shadow: 0 5px 14px rgb(29 70 95 / 5%);
  transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}

.manifest-card--selected {
  border-color: #28ae89;
  box-shadow: 0 0 0 3px rgb(39 199 154 / 12%), 0 8px 20px rgb(29 70 95 / 8%);
  transform: translateY(-2px);
}

.manifest-card[data-state="REJECTED"] {
  opacity: 0.62;
}

.manifest-card__main {
  display: grid;
  width: 100%;
  min-height: 178px;
  padding: 17px;
  border: 0;
  color: var(--ink);
  background:
    linear-gradient(145deg, rgb(39 199 154 / 5%), transparent 45%),
    #fff;
  text-align: left;
  cursor: pointer;
}

.manifest-card__main:disabled {
  cursor: default;
}

.manifest-card__status {
  justify-self: start;
  padding: 3px 7px;
  border: 1px solid #b9e4d6;
  border-radius: 10px;
  color: #147b5e;
  background: #ecfaf5;
  font-size: 9.5px;
  font-weight: 800;
}

.manifest-card[data-state="REGISTERED"] .manifest-card__status {
  border-color: var(--warning-line);
  color: #8a5a0a;
  background: var(--warning-bg);
}

.manifest-card[data-state="REJECTED"] .manifest-card__status {
  border-color: var(--danger-line);
  color: var(--danger);
  background: var(--danger-bg);
}

.manifest-card__main > strong {
  align-self: end;
  margin-top: 16px;
  color: var(--builder-navy);
  font-family: var(--font-mono);
  font-size: 31px;
  letter-spacing: -0.05em;
}

.manifest-card__main > small {
  color: var(--muted);
  font-size: 10px;
}

.manifest-card__path {
  margin-top: 14px;
  overflow: hidden;
  color: var(--ink);
  font-size: 11px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.manifest-card code {
  margin-top: 5px;
  color: var(--muted);
  font-size: 9.5px;
}

.manifest-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 44px;
  padding: 8px 12px;
  border-top: 1px solid #e6edf2;
  color: var(--muted);
  background: #f8fafc;
  font-size: 9.5px;
}

.chosen-mark {
  color: #158061;
  font-weight: 800;
}

.wizard-actions {
  justify-content: flex-end;
  gap: 12px;
  min-height: 54px;
  margin-top: 2px;
  padding-top: 16px;
  border-top: 1px solid #dce7ee;
}

.wizard-actions > span {
  margin-right: auto;
  color: var(--muted);
  font-size: 10.5px;
}

.launch-button b {
  margin-left: 10px;
  font-family: var(--font-mono);
}

.build-blueprint {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr);
  gap: 8px;
  align-items: stretch;
  padding: 17px;
  border: 1px solid #bad2df;
  border-radius: 5px;
  background:
    linear-gradient(90deg, rgb(9 91 132 / 4%) 1px, transparent 1px),
    linear-gradient(rgb(9 91 132 / 4%) 1px, transparent 1px),
    #f5fbfd;
  background-size: 16px 16px;
}

.blueprint-source,
.blueprint-process,
.blueprint-output {
  display: grid;
  align-content: center;
  gap: 7px;
  min-width: 0;
  min-height: 100px;
  padding: 14px;
  border: 1px solid #ccdee7;
  border-radius: 3px;
  background: rgb(255 255 255 / 91%);
}

.build-blueprint span,
.build-blueprint small {
  color: var(--muted);
  font-size: 9.5px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.build-blueprint strong {
  color: var(--builder-navy);
  font-size: 13px;
}

.build-blueprint code {
  overflow: hidden;
  color: #517488;
  font-size: 9.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.blueprint-arrow {
  align-self: center;
  color: var(--accent-deep) !important;
  font-family: var(--font-mono);
  font-size: 19px !important;
  text-align: center;
}

.build-track {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  margin: 8px 0;
  padding: 0;
  list-style: none;
}

.build-track li {
  position: relative;
  display: grid;
  justify-items: center;
  gap: 6px;
  color: var(--muted);
  text-align: center;
}

.build-track li:not(:last-child)::before {
  position: absolute;
  z-index: 0;
  top: 18px;
  left: calc(50% + 19px);
  width: calc(100% - 38px);
  height: 2px;
  background: #d6e1e7;
  content: "";
}

.build-track li[data-state="done"]:not(:last-child)::before {
  background: var(--builder-mint);
}

.build-track li > span {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 2px solid #c6d5dd;
  border-radius: 50%;
  color: #7f98a7;
  background: #f8fbfc;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 900;
}

.build-track li[data-state="done"] > span {
  border-color: var(--builder-mint);
  color: #fff;
  background: #20a980;
}

.build-track li[data-state="active"] > span {
  border-color: var(--accent);
  color: var(--accent-deep);
  background: #eef8ff;
  box-shadow: 0 0 0 6px rgb(39 156 241 / 11%);
  animation: builder-pulse 1.8s ease-in-out infinite;
}

.build-track li[data-state="failed"] > span {
  border-color: var(--danger);
  color: #fff;
  background: var(--danger);
}

.build-track strong {
  margin-top: 3px;
  color: var(--builder-navy);
  font-size: 11px;
}

.build-track small {
  color: var(--muted);
  font-size: 9.5px;
}

.version-beacon {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  min-width: 54px;
  height: 54px;
  margin-left: auto;
  border: 1px solid #bcd3df;
  border-radius: 50%;
  color: var(--builder-navy);
  background: #fff;
  box-shadow: 0 0 0 6px #edf5f8;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 900;
}

.version-beacon[data-state="FROZEN"] {
  border-color: #70cdb2;
  color: #147b5e;
  background: #eefaf6;
  box-shadow: 0 0 0 6px #ddf5ec;
}

.action-callout {
  gap: 15px;
  min-height: 92px;
  padding: 17px 19px;
  border: 1px solid #c9dce7;
  border-left: 4px solid var(--accent);
  border-radius: 4px;
  background: #f4faff;
}

.action-callout > div {
  display: grid;
  gap: 5px;
  min-width: 0;
  margin-right: auto;
}

.action-callout--success {
  border-color: #b9e4d6;
  border-left-color: var(--builder-mint);
  background: #f0fbf7;
}

.action-callout--review {
  border-color: var(--warning-line);
  border-left-color: var(--warning);
  background: #fffbf2;
}

.action-callout--review .action-callout__icon {
  background: var(--warning);
}

.action-callout--failed {
  border-color: var(--danger-line);
  border-left-color: var(--danger);
  background: var(--danger-bg);
}

.action-callout--failed .action-callout__icon {
  background: var(--danger);
}

.radar {
  position: relative;
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 1px solid #8cc9e9;
  border-radius: 50%;
  background: #e8f6fd;
}

.radar::before,
.radar::after {
  position: absolute;
  border: 1px solid rgb(39 156 241 / 30%);
  border-radius: 50%;
  content: "";
}

.radar::before { inset: 7px; }
.radar::after { inset: 14px; background: var(--accent); }

.radar i {
  position: absolute;
  width: 17px;
  height: 1px;
  background: var(--accent-deep);
  transform: translateX(8px) rotate(-28deg);
  transform-origin: left center;
  animation: radar-sweep 1.5s linear infinite;
}

.advanced-ledger {
  margin-top: 14px;
  overflow: hidden;
  border: 1px solid #d5e1e9;
  border-radius: 5px;
  background: #fff;
  box-shadow: var(--shadow-card);
}

.advanced-ledger summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 66px;
  padding: 14px 18px;
  color: var(--builder-navy);
  background: #f9fbfc;
  cursor: pointer;
  list-style: none;
}

.advanced-ledger summary::-webkit-details-marker { display: none; }

.advanced-ledger summary > span:first-child {
  display: grid;
  gap: 4px;
}

.advanced-ledger summary small,
.advanced-hint {
  color: var(--muted);
  font-size: 10.5px;
}

.advanced-ledger summary > span:last-child {
  color: var(--accent-ink);
  font-family: var(--font-mono);
  font-size: 10.5px;
}

.advanced-ledger__body {
  display: grid;
  gap: 13px;
  padding: 18px;
  border-top: 1px solid #e1e9ee;
}

.dataset-signature {
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid #dce7ed;
  border-radius: 3px;
  background: #f7fafc;
}

.dataset-signature > span {
  color: var(--muted);
  font-size: 10px;
}

.version-ledger .detection-row {
  width: 100%;
  cursor: pointer;
  text-align: left;
}

.detection-row--selected {
  border-left-color: var(--accent-deep) !important;
  background: var(--accent-soft) !important;
}

.row-actions {
  justify-content: flex-end;
  gap: 8px;
}

.wizard-enter-active,
.wizard-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
}

.wizard-enter-from {
  opacity: 0;
  transform: translateX(8px);
}

.wizard-leave-to {
  opacity: 0;
  transform: translateX(-6px);
}

@keyframes builder-pulse {
  50% { box-shadow: 0 0 0 7px rgb(39 199 154 / 8%); }
}

@keyframes radar-sweep {
  to { transform: translateX(8px) rotate(332deg); }
}

@media (prefers-reduced-motion: reduce) {
  .live-mark i,
  .build-track li[data-state="active"] > span,
  .radar i {
    animation: none;
  }
}

@media (max-width: 1120px) {
  .builder-board {
    grid-template-columns: 230px minmax(0, 1fr);
  }

  .manifest-gallery {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quick-create {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quick-create__title {
    grid-column: 1 / -1;
  }
}

@media (max-width: 820px) {
  .builder-board {
    grid-template-columns: 1fr;
  }

  .workflow-map {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    padding: 10px;
    overflow-x: auto;
  }

  .workflow-node {
    grid-template-columns: 32px minmax(82px, 1fr);
    min-height: 72px;
    padding: 8px;
  }

  .workflow-node:not(:last-child)::after,
  .workflow-node__signal {
    display: none;
  }

  .workflow-node__number {
    width: 32px;
    height: 32px;
  }

  .wizard-stage {
    padding: 22px;
  }

  .build-blueprint {
    grid-template-columns: 1fr;
  }

  .blueprint-arrow {
    transform: rotate(90deg);
  }

  .pane-metrics {
    display: none;
  }
}

@media (max-width: 620px) {
  .builder-heading,
  .builder-heading__aside,
  .selection-ticket,
  .wizard-actions,
  .action-callout,
  .visual-empty {
    align-items: stretch;
    flex-direction: column;
  }

  .builder-heading__aside {
    align-items: flex-start;
  }

  .workflow-map {
    grid-template-columns: repeat(4, 145px);
  }

  .wizard-stage {
    padding: 18px 14px;
  }

  .wizard-stage__header {
    align-items: flex-start;
  }

  .pane-intro {
    align-items: flex-start;
  }

  .manifest-gallery,
  .quick-create {
    grid-template-columns: 1fr;
  }

  .visual-empty {
    display: flex;
  }

  .selection-ticket code {
    width: 100%;
    margin-left: 0;
  }

  .build-track small {
    display: none;
  }

  .wizard-actions > span {
    margin-right: 0;
  }

  .row-actions {
    flex-wrap: wrap;
    justify-content: flex-start;
  }
}
</style>
