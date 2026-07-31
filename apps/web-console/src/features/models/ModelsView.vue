<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { ModelVersionPage, ModelVersionSummary } from './service'
import { ModelService } from './service'
import { DeploymentService } from './deployment-service'
import type {
  DeploymentApprovalRole,
  DeploymentEnvironment,
  DeploymentStrategy,
  DeploymentView,
} from './deployment-service'
import type { ModelDeploymentCreateRequest, RollbackRequest } from '@/api/generated'
import { useApplicationApiClient } from '@/api/runtime'

const api = useApplicationApiClient()
const service = new ModelService(api)
const deploymentService = new DeploymentService(api)
const modelId = ref('')
const page = ref<ModelVersionPage | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const approvalFilter = ref<'' | ModelVersionSummary['approval_state']>('')

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

const visibleItems = computed(() => {
  const items = page.value?.items ?? []
  return approvalFilter.value === ''
    ? items
    : items.filter((item) => item.approval_state === approvalFilter.value)
})

onMounted(() => {
  const queryModelId = new URLSearchParams(window.location.search).get('model_id')
  if (queryModelId !== null) modelId.value = queryModelId
  if (modelId.value !== '') void load()
})

async function load(cursor?: string): Promise<void> {
  if (modelId.value.trim() === '') {
    error.value = '请输入模型 ID；模型版本查询必须绑定模型范围'
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
  } catch {
    deploymentError.value = '回滚失败；后端只接受登记的已批准稳定目标'
  } finally {
    deploymentLoading.value = false
  }
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.trim())
}
</script>

<template>
  <section class="records-page">
    <header class="records-heading">
      <div>
        <p class="eyebrow">供应链证据 · 独立验证</p>
        <h2>模型版本管理</h2>
        <p class="muted">每次验证都绑定评估报告哈希；批准状态不能替代签名包和部署门禁。</p>
      </div>
      <span class="records-count">{{ visibleItems.length }} 条当前页版本</span>
    </header>

    <form class="filter-rail" aria-label="模型版本筛选" @submit.prevent="load()">
      <label>
        模型 ID
        <input v-model="modelId" maxlength="64" required placeholder="UUID" />
      </label>
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
      <button type="submit" class="primary-button compact">查询版本</button>
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
              v-if="item.approval_state === 'CANDIDATE' || item.approval_state === 'VALIDATED'"
              type="button"
              class="secondary-button"
              @click.stop="openDecisionForm(item)"
            >
              提交验证决定
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

      <form class="filter-rail" aria-label="创建模型部署" @submit.prevent="createDeployment">
        <label>当前模型 UUID<input v-model="deploymentModelVersionId" required placeholder="已批准模型版本" /></label>
        <label>回滚模型 UUID<input v-model="deploymentRollbackModelVersionId" required placeholder="不同的已批准版本" /></label>
        <label>环境<select v-model="deploymentEnvironment"><option value="SHADOW">影子</option><option value="CANARY">灰度</option><option value="PRODUCTION">生产</option></select></label>
        <label>策略<select v-model="deploymentStrategy"><option value="PERCENTAGE">按比例</option><option value="STATION">按工位</option></select></label>
        <label>流量比例<input v-model.number="deploymentTrafficRatio" type="number" min="0" max="1" step="0.01" required /></label>
        <label>工位 UUID（空格分隔）<input v-model="deploymentStationIds" placeholder="STATION 策略必填" /></label>
        <button class="primary-button compact" type="submit" :disabled="deploymentLoading">{{ deploymentLoading ? '提交中…' : '创建部署申请' }}</button>
      </form>

      <form class="filter-rail" aria-label="读取模型部署" @submit.prevent="refreshDeployment">
        <label>部署 UUID<input v-model="deploymentId" required placeholder="创建后自动填入" /></label>
        <button class="secondary-button compact" type="submit" :disabled="deploymentLoading">刷新状态</button>
        <span v-if="deploymentJobId !== null" class="decision-caveat">排队任务：{{ deploymentJobId }}</span>
      </form>

      <div v-if="deployment !== null" class="deployment-ledger">
        <dl class="version-grid">
          <dt>当前模型</dt><dd class="hash-text">{{ deployment.model_version_id }}</dd>
          <dt>状态</dt><dd>{{ deployment.status }}</dd>
          <dt>记录版本</dt><dd>{{ deployment.record_version }}（审批/回滚使用 If-Match）</dd>
          <dt>创建时间</dt><dd>{{ formatDate(deployment.created_at) }}</dd>
        </dl>

        <div v-if="deployment.status === 'REQUESTED'" class="review-decision-panel" style="position: static; margin-top: 16px">
          <h4>追加独立部署审批</h4>
          <div class="filter-rail">
            <label>角色<select v-model="approvalRole"><option value="QUALITY_APPROVER">质量审批人</option><option value="MODEL_RELEASE_APPROVER">模型发布审批人</option></select></label>
            <label>决定<select v-model="approvalDecision"><option value="APPROVE">批准</option><option value="REJECT">拒绝</option></select></label>
            <label>原因<input v-model="approvalReason" maxlength="2000" required placeholder="可审计原因" /></label>
            <label>输入部署 ID 二次确认<input v-model="deploymentConfirm" :placeholder="deployment.deployment_id" required /></label>
            <button type="button" class="primary-button compact" :disabled="deploymentLoading" @click="submitDeploymentApproval">提交审批</button>
          </div>
        </div>

        <div v-if="deployment.status === 'ACTIVE'" class="review-decision-panel" style="position: static; margin-top: 16px">
          <h4>生产回滚</h4>
          <p class="decision-caveat">回滚只影响新任务；历史任务版本和原始证据不可覆盖。</p>
          <div class="filter-rail">
            <label>目标模型 UUID<input v-model="rollbackTargetModelVersionId" required placeholder="登记的稳定版本" /></label>
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
