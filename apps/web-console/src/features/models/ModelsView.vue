<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type {
  ModelCatalogSummary,
  ModelVersionPage,
  ModelVersionSummary,
} from './service'
import { ModelService } from './service'
import { DeploymentService } from './deployment-service'
import type {
  DeploymentApprovalRole,
  DeploymentEnvironment,
  DeploymentPage,
  DeploymentSummary,
  DeploymentStrategy,
  DeploymentView,
} from './deployment-service'
import type { ModelDeploymentCreateRequest, RollbackRequest } from '@/api/generated'
import { useApplicationApiClient } from '@/api/runtime'
import { DatasetService } from '@/features/datasets/service'
import type { DatasetVersionSummary } from '@/features/datasets/service'
import { TrainingService } from '@/features/training/service'
import type { TrainingRunSummary } from '@/features/training/service'
import { useAuthStore } from '@/stores/auth'
import {
  buildModelRegistrationRequest,
  ModelRegistrationInputError,
} from './registration'

const api = useApplicationApiClient()
const service = new ModelService(api)
const deploymentService = new DeploymentService(api)
const datasetService = new DatasetService(api)
const trainingService = new TrainingService(api)
const auth = useAuthStore()
const modelId = ref('')
const modelCatalog = ref<readonly ModelCatalogSummary[]>([])
const catalogLoading = ref(false)
const modelName = ref('')
const modelTaskType = ref('classification-segmentation')
const modelCreating = ref(false)
const catalogNotice = ref<string | null>(null)
const page = ref<ModelVersionPage | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const approvalFilter = ref<'' | ModelVersionSummary['approval_state']>('')

const frozenDatasetVersions = ref<readonly DatasetVersionSummary[]>([])
const successfulTrainingRuns = ref<readonly TrainingRunSummary[]>([])
const registrationReferencesLoading = ref(false)
const registrationRunId = ref('')
const registryName = ref('tool-defect-multitask')
const registryVersion = ref('1')
const artifactBucket = ref('')
const artifactObjectKey = ref('')
const artifactSha256 = ref('')
const sbomSha256 = ref('')
const signatureKeyId = ref('')
const inputSpec = ref('{}')
const outputSpec = ref('{}')
const registrationEvaluationReportSha256 = ref('')
const thresholdGateSha256 = ref('')
const registrationSubmitting = ref(false)
const registrationError = ref<string | null>(null)
const registrationNotice = ref<string | null>(null)

const showDecisionForm = ref(false)
const decisionTarget = ref<ModelVersionSummary | null>(null)
const decisionValue = ref<'APPROVE' | 'REJECT'>('APPROVE')
const decisionReason = ref('')
const evaluationReportSha256 = ref('')
const decisionSubmitting = ref(false)
const decisionError = ref<string | null>(null)
const confirmText = ref('')
const confirmVisible = ref(false)

const deploymentId = ref('')
const deployment = ref<DeploymentView | null>(null)
const deploymentPage = ref<DeploymentPage | null>(null)
const deploymentStatusFilter = ref<'' | DeploymentSummary['status']>('')
const approvedModelVersions = ref<readonly ModelVersionSummary[]>([])
const deploymentEnvironment = ref<DeploymentEnvironment>('SHADOW')
const deploymentStrategy = ref<DeploymentStrategy>('PERCENTAGE')
const deploymentStationIds = ref('')
const deploymentTrafficRatio = ref(0)
const deploymentModelVersionId = ref('')
const deploymentRollbackModelVersionId = ref('')
const deploymentLoading = ref(false)
const deploymentError = ref<string | null>(null)
const deploymentJobId = ref<string | null>(null)
const approvalRole = ref<DeploymentApprovalRole>('QUALITY_APPROVER')
const approvalDecision = ref<'APPROVE' | 'REJECT'>('APPROVE')
const approvalReason = ref('')
const rollbackTargetModelVersionId = ref('')
const deploymentConfirm = ref('')

const selectedModel = computed(() =>
  modelCatalog.value.find((item) => item.model_id === modelId.value) ?? null,
)

const visibleItems = computed(() => {
  const items = page.value?.items ?? []
  return approvalFilter.value === ''
    ? items
    : items.filter((item) => item.approval_state === approvalFilter.value)
})

const selectedRegistrationRun = computed(() =>
  successfulTrainingRuns.value.find(
    (item) => item.training_run_id === registrationRunId.value,
  ) ?? null,
)

const registrationDatasetVersion = computed(() => {
  const datasetVersionId = selectedRegistrationRun.value?.dataset_version_id
  if (datasetVersionId === undefined) return null
  return frozenDatasetVersions.value.find(
    (item) => item.version_id === datasetVersionId,
  ) ?? null
})

const registrationReady = computed(() =>
  selectedModel.value !== null
  && selectedRegistrationRun.value !== null
  && registrationDatasetVersion.value !== null,
)

onMounted(() => {
  const queryModelId = new URLSearchParams(window.location.search).get('model_id')
  void initialize(queryModelId ?? undefined)
})

async function initialize(preferredModelId?: string): Promise<void> {
  await Promise.all([
    loadCatalog(preferredModelId),
    loadApprovedModelVersions(),
    loadDeployments(),
    loadRegistrationReferences(),
  ])
}

async function loadRegistrationReferences(): Promise<void> {
  registrationReferencesLoading.value = true
  registrationError.value = null
  try {
    const [datasets, runs] = await Promise.all([
      datasetService.listVersionCatalog({ status: 'FROZEN', pageSize: 200 }),
      trainingService.list({ status: 'SUCCEEDED', pageSize: 200 }),
    ])
    frozenDatasetVersions.value = datasets.items
    successfulTrainingRuns.value = runs.items
    if (
      !successfulTrainingRuns.value.some(
        (item) => item.training_run_id === registrationRunId.value,
      )
    ) {
      registrationRunId.value = successfulTrainingRuns.value[0]?.training_run_id ?? ''
    }
  } catch {
    frozenDatasetVersions.value = []
    successfulTrainingRuns.value = []
    registrationRunId.value = ''
    registrationError.value = '登记前置目录暂时无法读取'
  } finally {
    registrationReferencesLoading.value = false
  }
}

async function registerModelVersion(): Promise<void> {
  registrationError.value = null
  registrationNotice.value = null
  const run = selectedRegistrationRun.value
  const datasetVersion = registrationDatasetVersion.value
  if (selectedModel.value === null || run === null || datasetVersion === null) {
    registrationError.value = run === null
      ? '必须选择已成功完成的训练运行'
      : '训练运行引用的数据集版本不存在或尚未冻结'
    return
  }
  registrationSubmitting.value = true
  try {
    const response = await service.registerModelVersion(
      buildModelRegistrationRequest({
        modelId: modelId.value,
        trainingRunId: run.training_run_id,
        datasetVersionId: datasetVersion.version_id,
        registryName: registryName.value,
        registryVersion: registryVersion.value,
        artifactBucket: artifactBucket.value,
        artifactObjectKey: artifactObjectKey.value,
        artifactSha256: artifactSha256.value,
        sbomSha256: sbomSha256.value,
        signatureKeyId: signatureKeyId.value,
        inputSpec: inputSpec.value,
        outputSpec: outputSpec.value,
        evaluationReportSha256: registrationEvaluationReportSha256.value,
        thresholdGateSha256: thresholdGateSha256.value,
      }),
    )
    registrationNotice.value = `候选版本 v${response.version} 已登记：${response.model_version_id}`
    await loadCatalog(modelId.value)
  } catch (failure) {
    registrationError.value = failure instanceof ModelRegistrationInputError
      ? failure.message
      : '模型版本登记失败；后端未确认完整证据链时不会创建候选版本'
  } finally {
    registrationSubmitting.value = false
  }
}

async function loadCatalog(preferredModelId?: string): Promise<void> {
  catalogLoading.value = true
  error.value = null
  try {
    const catalog = await service.listModels({ pageSize: 200 })
    modelCatalog.value = catalog.items
    const candidate = preferredModelId
      ?? (modelCatalog.value.some((item) => item.model_id === modelId.value)
        ? modelId.value
        : modelCatalog.value[0]?.model_id)
    modelId.value = candidate ?? ''
    if (modelId.value !== '') await load()
    else page.value = null
  } catch {
    error.value = '模型目录暂时无法读取'
  } finally {
    catalogLoading.value = false
  }
}

async function createModel(): Promise<void> {
  error.value = null
  catalogNotice.value = null
  if (modelName.value.trim() === '' || modelTaskType.value.trim() === '') {
    error.value = '模型名称和任务类型均不能为空'
    return
  }
  modelCreating.value = true
  try {
    const created = await service.createModel({
      model_name: modelName.value.trim(),
      task_type: modelTaskType.value.trim(),
    })
    modelName.value = ''
    catalogNotice.value = `已创建模型 ${created.model_name}`
    await loadCatalog(created.model_id)
  } catch {
    error.value = '模型创建失败；请确认名称未被占用'
  } finally {
    modelCreating.value = false
  }
}

function selectModel(): void {
  approvalFilter.value = ''
  showDecisionForm.value = false
  void load()
}

async function loadApprovedModelVersions(): Promise<void> {
  try {
    approvedModelVersions.value = (
      await service.listModelVersions(undefined, {
        approvalState: 'APPROVED',
        pageSize: 100,
      })
    ).items
    if (deploymentModelVersionId.value === '') {
      deploymentModelVersionId.value = approvedModelVersions.value[0]?.model_version_id ?? ''
    }
    if (deploymentRollbackModelVersionId.value === '') {
      deploymentRollbackModelVersionId.value = approvedModelVersions.value[1]?.model_version_id ?? ''
    }
  } catch {
    approvedModelVersions.value = []
  }
}

async function loadDeployments(cursor?: string): Promise<void> {
  deploymentLoading.value = true
  deploymentError.value = null
  try {
    deploymentPage.value = await deploymentService.list({
      ...(deploymentStatusFilter.value === ''
        ? {}
        : { status: deploymentStatusFilter.value }),
      ...(cursor === undefined ? {} : { cursor }),
      pageSize: 50,
    })
  } catch {
    deploymentError.value = '部署目录暂时无法读取'
  } finally {
    deploymentLoading.value = false
  }
}

function selectDeployment(item: DeploymentSummary): void {
  deploymentId.value = item.deployment_id
  void refreshDeployment()
}

async function load(cursor?: string): Promise<void> {
  if (modelId.value.trim() === '') {
    page.value = null
    error.value = null
    return
  }
  loading.value = true
  error.value = null
  try {
    page.value = await service.listModelVersions(modelId.value.trim(), {
      pageSize: 25,
      ...(cursor === undefined ? {} : { cursor }),
    })
  } catch {
    error.value = '模型版本列表暂时无法读取'
  } finally {
    loading.value = false
  }
}

function approvalLabel(state: ModelVersionSummary['approval_state']): string {
  if (state === 'CANDIDATE') return '候选'
  if (state === 'VALIDATED') return '已验证'
  if (state === 'APPROVED') return '已批准'
  if (state === 'REJECTED') return '已驳回'
  return '已退役'
}

function shortId(value: string): string {
  return value.slice(0, 12)
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

function openDecisionForm(item: ModelVersionSummary): void {
  if (item.approval_state === 'APPROVED' || item.approval_state === 'RETIRED') return
  decisionTarget.value = item
  decisionValue.value = 'APPROVE'
  decisionReason.value = ''
  evaluationReportSha256.value = ''
  decisionError.value = null
  confirmText.value = ''
  confirmVisible.value = false
  showDecisionForm.value = true
}

function closeDecisionForm(): void {
  showDecisionForm.value = false
  decisionTarget.value = null
}

function prepareDeployment(item: ModelVersionSummary): void {
  deploymentModelVersionId.value = item.model_version_id
  if (deploymentRollbackModelVersionId.value === item.model_version_id) {
    deploymentRollbackModelVersionId.value = approvedModelVersions.value.find(
      (candidate) => candidate.model_version_id !== item.model_version_id,
    )?.model_version_id ?? ''
  }
}

function trySubmitDecision(): void {
  if (decisionReason.value.trim() === '') {
    decisionError.value = '验证决定必须填写原因'
    return
  }
  if (!/^[0-9a-f]{64}$/.test(evaluationReportSha256.value.trim())) {
    decisionError.value = '评估报告 SHA-256 必须是 64 位小写十六进制'
    return
  }
  confirmVisible.value = true
}

function confirmSubmitDecision(): void {
  if (confirmText.value.trim() !== decisionTarget.value?.registry_name) {
    decisionError.value = `请输入完整仓库名称“${decisionTarget.value?.registry_name ?? ''}”以确认`
    confirmVisible.value = false
    return
  }
  confirmVisible.value = false
  void executeDecision()
}

async function executeDecision(): Promise<void> {
  if (decisionTarget.value === null) return
  decisionSubmitting.value = true
  decisionError.value = null
  try {
    await service.submitValidationDecision(decisionTarget.value.model_version_id, {
      decision: decisionValue.value,
      reason: decisionReason.value.trim(),
      evaluation_report_sha256: evaluationReportSha256.value.trim(),
    })
    showDecisionForm.value = false
    decisionTarget.value = null
    await load()
    await loadApprovedModelVersions()
  } catch {
    decisionError.value = '验证决定提交失败；后端未批准时不得继续部署'
  } finally {
    decisionSubmitting.value = false
  }
}

async function createDeployment(): Promise<void> {
  deploymentError.value = null
  deploymentJobId.value = null
  const stations = deploymentStationIds.value
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter((item) => item !== '')
  if (!isUuid(deploymentModelVersionId.value) || !isUuid(deploymentRollbackModelVersionId.value)) {
    deploymentError.value = '当前模型和回滚模型都必须是 UUID'
    return
  }
  if (deploymentStrategy.value === 'STATION' && stations.length === 0) {
    deploymentError.value = '工位策略必须填写至少一个工位 UUID'
    return
  }
  if (deploymentEnvironment.value === 'SHADOW' && deploymentTrafficRatio.value !== 0) {
    deploymentError.value = '影子环境流量必须为 0'
    return
  }
  deploymentLoading.value = true
  try {
    const request = {
      model_version_id: deploymentModelVersionId.value.trim(),
      environment: deploymentEnvironment.value,
      strategy: deploymentStrategy.value,
      station_ids: stations,
      traffic_ratio: deploymentTrafficRatio.value,
      rollback_model_version_id: deploymentRollbackModelVersionId.value.trim(),
    } as unknown as ModelDeploymentCreateRequest
    const accepted = await deploymentService.create(request)
    deploymentJobId.value = accepted.job_id
    deploymentId.value = accepted.job_id
    deployment.value = await deploymentService.get(accepted.job_id)
    await loadDeployments()
  } catch {
    deploymentError.value = '部署申请被拒绝；请确认两个模型都已批准且回滚目标不同'
  } finally {
    deploymentLoading.value = false
  }
}

async function refreshDeployment(): Promise<void> {
  deploymentError.value = null
  if (!isUuid(deploymentId.value)) {
    deploymentError.value = '部署 ID 必须是 UUID'
    return
  }
  deploymentLoading.value = true
  try {
    deployment.value = await deploymentService.get(deploymentId.value.trim())
  } catch {
    deploymentError.value = '部署状态暂时无法读取'
  } finally {
    deploymentLoading.value = false
  }
}

async function submitDeploymentApproval(): Promise<void> {
  deploymentError.value = null
  if (deployment.value === null) return
  if (approvalReason.value.trim() === '') {
    deploymentError.value = '部署审批必须填写原因'
    return
  }
  if (deploymentConfirm.value.trim() !== deployment.value.deployment_id) {
    deploymentError.value = '请输入完整部署 ID 进行二次确认'
    return
  }
  deploymentLoading.value = true
  try {
    await deploymentService.approve(
      deployment.value.deployment_id,
      deployment.value.record_version,
      {
        role: approvalRole.value,
        decision: approvalDecision.value,
        reason: approvalReason.value.trim(),
      },
    )
    approvalReason.value = ''
    deploymentConfirm.value = ''
    await refreshDeployment()
    await loadDeployments()
  } catch {
    deploymentError.value = '部署审批失败；可能是版本已变化或职责分离校验未通过'
  } finally {
    deploymentLoading.value = false
  }
}

async function rollbackDeployment(): Promise<void> {
  deploymentError.value = null
  if (deployment.value === null || deployment.value.status !== 'ACTIVE') {
    deploymentError.value = '只有 ACTIVE 部署可以回滚'
    return
  }
  if (!isUuid(rollbackTargetModelVersionId.value) || rollbackTargetModelVersionId.value.trim() === deployment.value.model_version_id) {
    deploymentError.value = '回滚目标必须是不同的 UUID'
    return
  }
  if (deploymentConfirm.value.trim() !== deployment.value.deployment_id) {
    deploymentError.value = '请输入完整部署 ID 进行二次确认'
    return
  }
  deploymentLoading.value = true
  try {
    const request = {
      target_model_version_id: rollbackTargetModelVersionId.value.trim(),
      reason: approvalReason.value.trim(),
    } as unknown as RollbackRequest
    await deploymentService.rollback(
      deployment.value.deployment_id,
      deployment.value.record_version,
      request,
    )
    deploymentConfirm.value = ''
    await refreshDeployment()
    await loadDeployments()
  } catch {
    deploymentError.value = '回滚失败；后端只接受登记的已批准稳定目标'
  } finally {
    deploymentLoading.value = false
  }
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.trim())
}
</script>

<template>
  <section class="records-page">
    <header class="records-heading">
      <div>
        <p class="eyebrow">供应链证据 · 独立验证</p>
        <h2>模型版本管理</h2>
        <p class="muted">从模型目录进入版本、审批与部署记录，不再依赖外部保存 UUID。</p>
      </div>
      <span class="records-count">{{ modelCatalog.length }} 个模型 · {{ visibleItems.length }} 个版本</span>
    </header>

    <section class="resource-directory" aria-labelledby="model-directory-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">资源目录</p>
          <h3 id="model-directory-title">选择模型</h3>
        </div>
        <button type="button" class="text-button" :disabled="catalogLoading" @click="loadCatalog()">刷新目录</button>
      </div>
      <div v-if="catalogLoading" class="loading-ledger" role="status">正在读取模型目录…</div>
      <template v-else>
        <div class="resource-directory__rail">
          <label>
            模型
            <select v-model="modelId" :disabled="modelCatalog.length === 0" @change="selectModel">
              <option value="" disabled>{{ modelCatalog.length === 0 ? '暂无模型' : '请选择模型' }}</option>
              <option v-for="item in modelCatalog" :key="item.model_id" :value="item.model_id">
                {{ item.model_name }} · {{ item.version_count }} 个版本
              </option>
            </select>
          </label>
          <div v-if="selectedModel !== null" class="resource-identity">
            <span>模型 ID</span>
            <strong class="hash-text">{{ selectedModel.model_id }}</strong>
            <small>{{ selectedModel.task_type }} · 创建于 {{ formatDate(selectedModel.created_at) }}</small>
          </div>
          <div v-else class="empty-catalog">
            <strong>目录为空</strong>
            <span>先创建模型目录项，再登记带完整供应链证据的版本。</span>
          </div>
        </div>

        <form
          v-if="auth.hasPermission('model:register')"
          class="catalog-create-form"
          aria-label="新建模型"
          @submit.prevent="createModel"
        >
          <div>
            <span class="catalog-create-form__index">＋</span>
            <div><strong>新建模型</strong><small>创建稳定模型 ID，不登记或批准任何制品。</small></div>
          </div>
          <label>名称<input v-model="modelName" maxlength="128" required placeholder="例如：刀具缺陷多任务模型" /></label>
          <label>任务类型<input v-model="modelTaskType" maxlength="64" required /></label>
          <button type="submit" class="primary-button compact" :disabled="modelCreating">
            {{ modelCreating ? '创建中…' : '创建模型' }}
          </button>
        </form>
        <p v-if="catalogNotice !== null" class="panel-notice" role="status">{{ catalogNotice }}</p>
      </template>
    </section>

    <section
      v-if="auth.hasPermission('model:register')"
      class="resource-directory model-registration"
      aria-labelledby="model-registration-title"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">受控制品 · 安全失败</p>
          <h3 id="model-registration-title">导入已验证模型包</h3>
        </div>
        <button
          type="button"
          class="text-button"
          :disabled="registrationReferencesLoading"
          @click="loadRegistrationReferences"
        >
          刷新前置条件
        </button>
      </div>

      <div class="model-registration__warning">
        <strong>这里不上传或拼装本地权重。</strong>
        <span>请先由训练/发布服务完成模型包校验、签名和对象存储上传，再登记不可变对象引用。</span>
      </div>

      <ol class="model-registration__steps" aria-label="模型登记阶段">
        <li :data-state="selectedModel === null ? 'blocked' : 'ready'"><span>01</span><strong>选择模型</strong><small>{{ selectedModel?.model_name ?? '未选择' }}</small></li>
        <li :data-state="selectedRegistrationRun === null ? 'blocked' : 'ready'"><span>02</span><strong>绑定训练</strong><small>{{ selectedRegistrationRun === null ? '缺少成功运行' : shortId(selectedRegistrationRun.training_run_id) }}</small></li>
        <li :data-state="registrationDatasetVersion === null ? 'blocked' : 'ready'"><span>03</span><strong>核对数据</strong><small>{{ registrationDatasetVersion === null ? '未冻结或不匹配' : `冻结 v${registrationDatasetVersion.version}` }}</small></li>
        <li data-state="pending"><span>04</span><strong>登记候选</strong><small>提交后进入 CANDIDATE</small></li>
      </ol>

      <form class="model-registration__form" aria-label="登记模型版本" @submit.prevent="registerModelVersion">
        <fieldset>
          <legend>来源绑定</legend>
          <label>
            已成功训练运行
            <select v-model="registrationRunId" required :disabled="registrationReferencesLoading || successfulTrainingRuns.length === 0">
              <option value="" disabled>{{ successfulTrainingRuns.length === 0 ? '暂无成功训练运行' : '请选择训练运行' }}</option>
              <option v-for="item in successfulTrainingRuns" :key="item.training_run_id" :value="item.training_run_id">
                {{ item.training_config_version }} · {{ shortId(item.training_run_id) }}
              </option>
            </select>
          </label>
          <label>
            自动绑定的冻结数据集
            <input
              :value="registrationDatasetVersion === null ? '' : `${registrationDatasetVersion.version_id} · v${registrationDatasetVersion.version}`"
              readonly
              :placeholder="selectedRegistrationRun === null ? '先选择训练运行' : '该运行的数据集尚未冻结'"
            />
          </label>
          <label>注册表名称<input v-model="registryName" required maxlength="256" /></label>
          <label>注册表版本<input v-model="registryVersion" required maxlength="128" /></label>
        </fieldset>

        <fieldset>
          <legend>不可变制品</legend>
          <label>模型制品桶<input v-model="artifactBucket" required maxlength="128" placeholder="例如：td-models" /></label>
          <label class="span-two">完整模型包对象键<input v-model="artifactObjectKey" required maxlength="1024" placeholder="models/…/package.tar.gz；不能填写单个 weights.h5" /></label>
          <label class="span-two">模型包 SHA-256<input v-model="artifactSha256" required maxlength="64" pattern="[0-9a-f]{64}" placeholder="64 位小写十六进制" /></label>
          <label class="span-two">SBOM SHA-256<input v-model="sbomSha256" required maxlength="64" pattern="[0-9a-f]{64}" placeholder="64 位小写十六进制" /></label>
          <label>签名密钥 ID<input v-model="signatureKeyId" required maxlength="256" /></label>
        </fieldset>

        <fieldset>
          <legend>运行规格与评估证据</legend>
          <label class="span-two">输入规格 JSON<textarea v-model="inputSpec" required rows="4" spellcheck="false" /></label>
          <label class="span-two">输出规格 JSON<textarea v-model="outputSpec" required rows="4" spellcheck="false" /></label>
          <label class="span-two">评估报告 SHA-256<input v-model="registrationEvaluationReportSha256" required maxlength="64" pattern="[0-9a-f]{64}" /></label>
          <label class="span-two">门槛报告 SHA-256<input v-model="thresholdGateSha256" required maxlength="64" pattern="[0-9a-f]{64}" /></label>
        </fieldset>

        <div class="model-registration__action">
          <p>提交只创建候选版本，不会批准、部署或切换生产流量。</p>
          <button class="primary-button compact" type="submit" :disabled="registrationSubmitting || !registrationReady">
            {{ registrationSubmitting ? '登记中…' : '登记为候选版本' }}
          </button>
        </div>
      </form>

      <p v-if="successfulTrainingRuns.length === 0 && !registrationReferencesLoading" class="decision-caveat">
        当前没有成功训练运行；请先完成真实训练，不能用排队、运行中或失败记录登记模型。
      </p>
      <p v-if="registrationNotice !== null" class="panel-notice hash-text" role="status">{{ registrationNotice }}</p>
      <p v-if="registrationError !== null" class="panel-error" role="alert">{{ registrationError }}</p>
    </section>

    <form class="filter-rail" aria-label="模型版本筛选" @submit.prevent="load()">
      <label>
        审批状态
        <select v-model="approvalFilter">
          <option value="">全部</option>
          <option value="CANDIDATE">候选</option>
          <option value="VALIDATED">已验证</option>
          <option value="APPROVED">已批准</option>
          <option value="REJECTED">已驳回</option>
          <option value="RETIRED">已退役</option>
        </select>
      </label>
      <button type="submit" class="secondary-button compact" :disabled="modelId === ''">刷新版本</button>
    </form>

    <p v-if="error !== null" class="panel-error" role="alert">{{ error }}</p>
    <div v-else-if="loading" class="loading-ledger" role="status">正在读取模型版本…</div>
    <div v-else-if="page !== null && visibleItems.length === 0" class="loading-ledger">没有匹配的模型版本</div>

    <ol v-else-if="page !== null" class="detection-ledger">
      <li v-for="item in visibleItems" :key="item.model_version_id">
        <div class="detection-row">
          <span class="detection-row__index" aria-hidden="true">M</span>
          <span>
            <strong>v{{ item.version }} · {{ item.registry_name }}</strong>
            <small>{{ item.registry_version }} · {{ formatDate(item.created_at) }}</small>
          </span>
          <span>
            <small class="hash-text">ID {{ shortId(item.model_version_id) }}</small>
          </span>
          <span
            class="state-stamp"
            :data-state="item.approval_state === 'APPROVED' ? 'FINALIZED' : item.approval_state === 'REJECTED' ? 'FAILED' : item.approval_state === 'RETIRED' ? 'DEAD' : ''"
          >
            {{ approvalLabel(item.approval_state) }}
          </span>
          <span>
            <button
              v-if="auth.hasPermission('model:validate') && (item.approval_state === 'CANDIDATE' || item.approval_state === 'VALIDATED')"
              type="button"
              class="secondary-button"
              @click.stop="openDecisionForm(item)"
            >
              提交验证决定
            </button>
            <button
              v-else-if="auth.hasPermission('model:deploy:execute') && item.approval_state === 'APPROVED'"
              type="button"
              class="secondary-button"
              @click.stop="prepareDeployment(item)"
            >
              用于部署
            </button>
            <span v-else aria-hidden="true">—</span>
          </span>
        </div>
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

    <div
      v-if="showDecisionForm && decisionTarget !== null"
      class="review-decision-panel"
      style="position: static; margin-top: 16px"
    >
      <div class="section-heading">
        <h3>验证 {{ decisionTarget.registry_name }} v{{ decisionTarget.version }}</h3>
        <button type="button" class="text-button" @click="closeDecisionForm">取消</button>
      </div>

      <p class="decision-caveat">验证决定只推进模型审批状态，不直接切换生产流量。</p>
      <p v-if="decisionError !== null" class="panel-error" role="alert">{{ decisionError }}</p>

      <fieldset>
        <legend>验证决定</legend>
        <label><input v-model="decisionValue" type="radio" value="APPROVE" name="validation-decision" />通过当前阶段</label>
        <label><input v-model="decisionValue" type="radio" value="REJECT" name="validation-decision" />拒绝</label>
      </fieldset>

      <label>
        决定原因
        <textarea v-model="decisionReason" rows="3" maxlength="2000" required placeholder="填写可审计的技术或质量依据" />
      </label>
      <label>
        评估报告 SHA-256
        <input v-model="evaluationReportSha256" maxlength="64" pattern="[0-9a-f]{64}" required placeholder="64 位小写十六进制" />
      </label>

      <button
        type="button"
        class="primary-button compact"
        :disabled="decisionSubmitting"
        @click="trySubmitDecision"
      >
        {{ decisionSubmitting ? '提交中…' : '继续确认' }}
      </button>
    </div>

    <div v-if="confirmVisible && decisionTarget !== null" class="claim-gate">
      <div>
        <strong>确认提交验证决定？</strong>
        <p>后端将再次校验评估报告哈希、审批状态和职责分离；验证通过不等于生产放行。</p>
      </div>
      <label>
        输入仓库名称确认
        <input v-model="confirmText" :placeholder="decisionTarget.registry_name" />
      </label>
      <div style="display: flex; gap: 8px">
        <button type="button" class="primary-button compact" @click="confirmSubmitDecision">确认执行</button>
        <button type="button" class="secondary-button" @click="confirmVisible = false">取消</button>
      </div>
    </div>

    <section class="panel" style="margin-top: 24px" aria-label="模型部署控制">
      <div class="section-heading">
        <div>
          <p class="eyebrow">双人审批 · 灰度护栏</p>
          <h3>部署与回滚</h3>
        </div>
        <span v-if="deployment !== null" class="state-stamp">{{ deployment.status }}</span>
      </div>
      <p class="muted">创建、审批和回滚均由后端再次验证模型批准状态；页面只提交意图，不直接改变最终处置规则。</p>

      <form
        v-if="auth.hasPermission('model:deploy:execute')"
        class="filter-rail"
        aria-label="创建模型部署"
        @submit.prevent="createDeployment"
      >
        <label>
          当前模型版本
          <select v-model="deploymentModelVersionId" required>
            <option value="" disabled>请选择已批准版本</option>
            <option v-for="item in approvedModelVersions" :key="item.model_version_id" :value="item.model_version_id">
              {{ item.registry_name }} · {{ item.registry_version }}
            </option>
          </select>
        </label>
        <label>
          回滚模型版本
          <select v-model="deploymentRollbackModelVersionId" required>
            <option value="" disabled>请选择不同的稳定版本</option>
            <option
              v-for="item in approvedModelVersions.filter((candidate) => candidate.model_version_id !== deploymentModelVersionId)"
              :key="item.model_version_id"
              :value="item.model_version_id"
            >
              {{ item.registry_name }} · {{ item.registry_version }}
            </option>
          </select>
        </label>
        <label>环境<select v-model="deploymentEnvironment"><option value="SHADOW">影子</option><option value="CANARY">灰度</option><option value="PRODUCTION">生产</option></select></label>
        <label>策略<select v-model="deploymentStrategy"><option value="PERCENTAGE">按比例</option><option value="STATION">按工位</option></select></label>
        <label>流量比例<input v-model.number="deploymentTrafficRatio" type="number" min="0" max="1" step="0.01" required /></label>
        <label>工位 UUID（空格分隔）<input v-model="deploymentStationIds" placeholder="STATION 策略必填" /></label>
        <button class="primary-button compact" type="submit" :disabled="deploymentLoading || approvedModelVersions.length < 2">{{ deploymentLoading ? '提交中…' : '创建部署申请' }}</button>
      </form>

      <div class="deployment-directory" aria-label="部署记录目录">
        <div class="section-heading">
          <h4>部署记录</h4>
          <button type="button" class="text-button" :disabled="deploymentLoading" @click="loadDeployments()">刷新目录</button>
        </div>
        <div class="filter-rail">
          <label>
            状态
            <select v-model="deploymentStatusFilter" @change="loadDeployments()">
              <option value="">全部状态</option>
              <option value="REQUESTED">待审批</option>
              <option value="APPROVED">已批准</option>
              <option value="ACTIVE">生效中</option>
              <option value="ROLLED_BACK">已回滚</option>
              <option value="REJECTED">已拒绝</option>
            </select>
          </label>
          <span v-if="deploymentJobId !== null" class="decision-caveat">排队任务：{{ deploymentJobId }}</span>
        </div>
        <div v-if="deploymentLoading && deploymentPage === null" class="loading-ledger" role="status">正在读取部署记录…</div>
        <div v-else-if="deploymentPage?.items.length === 0" class="empty-catalog">
          <strong>暂无部署记录</strong>
          <span>部署申请创建后会自动进入此目录。</span>
        </div>
        <ol v-else class="detection-ledger">
          <li v-for="item in deploymentPage?.items ?? []" :key="item.deployment_id">
            <button type="button" class="detection-row" @click="selectDeployment(item)">
              <span class="detection-row__index" aria-hidden="true">DP</span>
              <span><strong>{{ item.environment }} · {{ item.strategy }}</strong><small>{{ formatDate(item.created_at) }}</small></span>
              <span class="hash-text">{{ item.model_version_id.slice(0, 12) }}</span>
              <span class="state-stamp">{{ item.status }}</span>
              <span aria-hidden="true">→</span>
            </button>
          </li>
        </ol>
        <footer v-if="deploymentPage?.has_more" class="pager">
          <button
            type="button"
            class="secondary-button"
            :disabled="deploymentLoading || deploymentPage.next_cursor === null"
            @click="deploymentPage.next_cursor && loadDeployments(deploymentPage.next_cursor)"
          >
            下一页
          </button>
        </footer>
      </div>

      <div v-if="deployment !== null" class="deployment-ledger">
        <dl class="version-grid">
          <dt>部署 ID</dt><dd class="hash-text">{{ deployment.deployment_id }}</dd>
          <dt>当前模型</dt><dd class="hash-text">{{ deployment.model_version_id }}</dd>
          <dt>状态</dt><dd>{{ deployment.status }}</dd>
          <dt>记录版本</dt><dd>{{ deployment.record_version }}（审批/回滚使用 If-Match）</dd>
          <dt>创建时间</dt><dd>{{ formatDate(deployment.created_at) }}</dd>
        </dl>
        <button type="button" class="secondary-button compact" :disabled="deploymentLoading" @click="refreshDeployment">刷新当前记录</button>

        <div
          v-if="deployment.status === 'REQUESTED' && (auth.hasPermission('dataset:approve') || auth.hasPermission('model:deploy:approve'))"
          class="review-decision-panel"
          style="position: static; margin-top: 16px"
        >
          <h4>追加独立部署审批</h4>
          <div class="filter-rail">
            <label>角色<select v-model="approvalRole"><option value="QUALITY_APPROVER">质量审批人</option><option value="MODEL_RELEASE_APPROVER">模型发布审批人</option></select></label>
            <label>决定<select v-model="approvalDecision"><option value="APPROVE">批准</option><option value="REJECT">拒绝</option></select></label>
            <label>原因<input v-model="approvalReason" maxlength="2000" required placeholder="可审计原因" /></label>
            <label>输入部署 ID 二次确认<input v-model="deploymentConfirm" :placeholder="deployment.deployment_id" required /></label>
            <button type="button" class="primary-button compact" :disabled="deploymentLoading" @click="submitDeploymentApproval">提交审批</button>
          </div>
        </div>

        <div v-if="deployment.status === 'ACTIVE' && auth.hasPermission('model:rollback')" class="review-decision-panel" style="position: static; margin-top: 16px">
          <h4>生产回滚</h4>
          <p class="decision-caveat">回滚只影响新任务；历史任务版本和原始证据不可覆盖。</p>
          <div class="filter-rail">
            <label>
              目标模型版本
              <select v-model="rollbackTargetModelVersionId" required>
                <option value="" disabled>请选择回滚版本</option>
                <option
                  v-for="item in approvedModelVersions.filter((candidate) => candidate.model_version_id !== deployment?.model_version_id)"
                  :key="item.model_version_id"
                  :value="item.model_version_id"
                >
                  {{ item.registry_name }} · {{ item.registry_version }}
                </option>
              </select>
            </label>
            <label>回滚原因<input v-model="approvalReason" maxlength="2000" required placeholder="指标门槛或故障依据" /></label>
            <label>输入部署 ID 二次确认<input v-model="deploymentConfirm" :placeholder="deployment.deployment_id" required /></label>
            <button type="button" class="primary-button compact" :disabled="deploymentLoading" @click="rollbackDeployment">创建回滚任务</button>
          </div>
        </div>
      </div>
      <p v-if="deploymentError !== null" class="panel-error" role="alert">{{ deploymentError }}</p>
    </section>
  </section>
</template>
