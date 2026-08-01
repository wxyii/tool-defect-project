<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { useApplicationApiClient } from '@/api/runtime'
import type { Uuid } from '@/api/generated'
import { useAuthStore } from '@/stores/auth'
import { DatasetService } from '@/features/datasets/service'
import type { DatasetVersionSummary } from '@/features/datasets/service'
import { ModelService } from '@/features/models/service'
import type { ModelVersionSummary } from '@/features/models/service'
import { TrainingService } from './service'
import type { TrainingRunPage, TrainingRunSummary } from './service'

const api = useApplicationApiClient()
const service = new TrainingService(api)
const datasets = new DatasetService(api)
const models = new ModelService(api)
const auth = useAuthStore()

const datasetVersions = ref<readonly DatasetVersionSummary[]>([])
const approvedModelVersions = ref<readonly ModelVersionSummary[]>([])
const referencesLoading = ref(false)
const datasetVersionId = ref('')
const initialModelVersionId = ref('')
const trainingConfigVersion = ref('')
const page = ref<TrainingRunPage | null>(null)
const selectedRun = ref<TrainingRunSummary | null>(null)
const statusFilter = ref<'' | TrainingRunSummary['status']>('')
const jobId = ref<string | null>(null)
const creating = ref(false)
const loading = ref(false)
const error = ref<string | null>(null)

onMounted(() => {
  void loadReferences()
  void loadRuns()
})

async function loadReferences(): Promise<void> {
  referencesLoading.value = true
  try {
    const [datasetPage, modelPage] = await Promise.all([
      datasets.listVersionCatalog({ status: 'FROZEN', pageSize: 200 }),
      models.listModelVersions(undefined, {
        approvalState: 'APPROVED',
        pageSize: 100,
      }),
    ])
    datasetVersions.value = datasetPage.items
    approvedModelVersions.value = modelPage.items
    if (datasetVersionId.value === '') {
      datasetVersionId.value = datasetVersions.value[0]?.version_id ?? ''
    }
  } catch {
    error.value = '训练引用目录暂时无法读取'
  } finally {
    referencesLoading.value = false
  }
}

async function loadRuns(cursor?: string): Promise<void> {
  loading.value = true
  error.value = null
  try {
    page.value = await service.list({
      ...(statusFilter.value === '' ? {} : { status: statusFilter.value }),
      ...(cursor === undefined ? {} : { cursor }),
      pageSize: 50,
    })
    if (
      selectedRun.value !== null
      && !page.value.items.some(
        (item) => item.training_run_id === selectedRun.value?.training_run_id,
      )
    ) {
      selectedRun.value = null
    }
  } catch {
    error.value = '训练运行目录暂时无法读取'
  } finally {
    loading.value = false
  }
}

async function createRun(): Promise<void> {
  error.value = null
  jobId.value = null
  if (datasetVersionId.value === '' || trainingConfigVersion.value.trim() === '') {
    error.value = '请选择已冻结的数据集版本并填写训练配置版本'
    return
  }
  creating.value = true
  try {
    const accepted = await service.create({
      dataset_version_id: datasetVersionId.value as Uuid,
      initial_model_version_id: initialModelVersionId.value === ''
        ? null
        : initialModelVersionId.value as Uuid,
      training_config_version: trainingConfigVersion.value.trim(),
    })
    jobId.value = accepted.job_id
    await loadRuns()
    selectedRun.value = page.value?.items.find(
      (item) => item.training_run_id === accepted.job_id,
    ) ?? null
  } catch {
    error.value = '训练任务创建失败；请确认运行锁已配置且数据集仍为冻结状态'
  } finally {
    creating.value = false
  }
}

function statusLabel(status: TrainingRunSummary['status']): string {
  if (status === 'QUEUED') return '排队中'
  if (status === 'RUNNING') return '运行中'
  if (status === 'SUCCEEDED') return '已成功'
  if (status === 'FAILED') return '已失败'
  return '已取消'
}

function formatDate(iso: string | null): string {
  if (iso === null) return '尚未记录'
  const date = new Date(iso)
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN') : iso
}
</script>

<template>
  <section class="records-page">
    <header class="records-heading">
      <div>
        <p class="eyebrow">可复现训练 · 版本锁定</p>
        <h2>训练运行</h2>
        <p class="muted">从已登记资源中选择输入，并在同一页面查看全部运行记录。</p>
      </div>
      <span class="records-count">{{ page?.items.length ?? 0 }} 条当前页运行</span>
    </header>

    <form
      v-if="auth.hasPermission('training:create')"
      class="resource-directory"
      aria-label="创建训练运行"
      @submit.prevent="createRun"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">新建任务</p>
          <h3>创建离线训练运行</h3>
        </div>
        <span class="state-stamp">异步执行</span>
      </div>
      <div class="resource-directory__rail resource-directory__rail--wide">
        <label>
          已冻结数据集版本
          <select v-model="datasetVersionId" required :disabled="referencesLoading || datasetVersions.length === 0">
            <option value="" disabled>{{ datasetVersions.length === 0 ? '暂无可训练版本' : '请选择数据集版本' }}</option>
            <option v-for="item in datasetVersions" :key="item.version_id" :value="item.version_id">
              数据集 {{ item.dataset_id.slice(0, 8) }} · v{{ item.version }} · {{ item.sample_count }} 个样本
            </option>
          </select>
        </label>
        <label>
          初始化模型版本（可选）
          <select v-model="initialModelVersionId" :disabled="referencesLoading">
            <option value="">从头训练</option>
            <option v-for="item in approvedModelVersions" :key="item.model_version_id" :value="item.model_version_id">
              {{ item.registry_name }} · {{ item.registry_version }}
            </option>
          </select>
        </label>
        <label>
          训练配置版本
          <input v-model="trainingConfigVersion" required maxlength="128" placeholder="例如：multitask/2026.08.01" />
        </label>
        <button class="primary-button compact" type="submit" :disabled="creating || datasetVersions.length === 0">
          {{ creating ? '提交中…' : '创建训练任务' }}
        </button>
      </div>
      <p v-if="datasetVersions.length === 0 && !referencesLoading" class="decision-caveat">
        当前没有已冻结数据集版本，请先在“数据集”页面完成候选清单构建与审批。
      </p>
      <p v-if="jobId !== null" class="panel-notice" role="status">
        已创建排队任务：<span class="hash-text">{{ jobId }}</span>
      </p>
    </form>

    <section class="resource-directory" aria-labelledby="training-directory-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">运行目录</p>
          <h3 id="training-directory-title">训练记录</h3>
        </div>
        <button type="button" class="text-button" :disabled="loading" @click="loadRuns()">刷新目录</button>
      </div>
      <div class="filter-rail">
        <label>
          状态
          <select v-model="statusFilter" @change="loadRuns()">
            <option value="">全部状态</option>
            <option value="QUEUED">排队中</option>
            <option value="RUNNING">运行中</option>
            <option value="SUCCEEDED">已成功</option>
            <option value="FAILED">已失败</option>
            <option value="CANCELLED">已取消</option>
          </select>
        </label>
      </div>

      <div v-if="loading" class="loading-ledger" role="status">正在读取训练运行…</div>
      <div v-else-if="page?.items.length === 0" class="empty-catalog">
        <strong>暂无训练运行</strong>
        <span>创建后的任务会自动出现在这里，不需要再记录或手填运行 UUID。</span>
      </div>
      <ol v-else class="detection-ledger">
        <li v-for="item in page?.items ?? []" :key="item.training_run_id">
          <button type="button" class="detection-row" @click="selectedRun = item">
            <span class="detection-row__index" aria-hidden="true">TR</span>
            <span>
              <strong>{{ item.training_config_version }}</strong>
              <small>数据集版本 {{ item.dataset_version_id.slice(0, 12) }} · {{ formatDate(item.created_at) }}</small>
            </span>
            <span class="hash-text">{{ item.training_run_id.slice(0, 12) }}</span>
            <span class="state-stamp" :data-state="item.status === 'SUCCEEDED' ? 'FINALIZED' : item.status === 'FAILED' ? 'FAILED' : ''">
              {{ statusLabel(item.status) }}
            </span>
            <span aria-hidden="true">→</span>
          </button>
        </li>
      </ol>
      <footer v-if="page?.has_more" class="pager">
        <button
          type="button"
          class="secondary-button"
          :disabled="loading || page.next_cursor === null"
          @click="page.next_cursor && loadRuns(page.next_cursor)"
        >
          下一页
        </button>
      </footer>
    </section>

    <section v-if="selectedRun !== null" class="detail-section" aria-label="训练运行详情">
      <div class="section-heading">
        <h3>运行证据</h3>
        <button type="button" class="text-button" @click="selectedRun = null">关闭</button>
      </div>
      <dl class="version-grid">
        <dt>运行 ID</dt><dd class="hash-text">{{ selectedRun.training_run_id }}</dd>
        <dt>数据集版本</dt><dd class="hash-text">{{ selectedRun.dataset_version_id }}</dd>
        <dt>初始化模型</dt><dd class="hash-text">{{ selectedRun.initial_model_version_id ?? '从头训练' }}</dd>
        <dt>配置版本</dt><dd>{{ selectedRun.training_config_version }}</dd>
        <dt>状态</dt><dd>{{ statusLabel(selectedRun.status) }}</dd>
        <dt>开始时间</dt><dd>{{ formatDate(selectedRun.started_at) }}</dd>
        <dt>结束时间</dt><dd>{{ formatDate(selectedRun.finished_at) }}</dd>
        <dt>失败代码</dt><dd>{{ selectedRun.failure_code ?? '无' }}</dd>
      </dl>
    </section>

    <p v-if="error !== null" class="panel-error" role="alert">{{ error }}</p>
  </section>
</template>
