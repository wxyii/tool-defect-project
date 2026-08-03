<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { apiErrorMessage } from '@/api/errors'
import { useApplicationApiClient } from '@/api/runtime'
import {
  CANDIDATE_STATUSES,
  SAMPLE_LABELS,
  SampleLibraryService,
  type AdminDetectionItem,
  type CandidateDecision,
  type SampleCandidate,
  type SampleExportJob,
  type SampleLabel,
} from './service'

const service = new SampleLibraryService(useApplicationApiClient())
const items = ref<readonly AdminDetectionItem[]>([])
const candidates = ref<readonly SampleCandidate[]>([])
const selectedCandidateIds = ref<string[]>([])
const selectedLabel = ref<SampleLabel | ''>('')
const selectedStatus = ref('')
const selectedStage = ref('')
const adminNextCursor = ref<string | undefined>()
const candidateNextCursor = ref<string | undefined>()
const feedbackLabel = ref<Record<string, SampleLabel | ''>>({})
const feedbackNote = ref<Record<string, string>>({})
const loading = ref(false)
const savingItemId = ref<string | null>(null)
const decidingCandidateId = ref<string | null>(null)
const error = ref<string | null>(null)
const exportJob = ref<SampleExportJob | null>(null)
const downloadUrl = ref<string | null>(null)
const receiptReceiver = ref('')
const receiptReference = ref('')
const receiptNote = ref('')
const recordingReceipt = ref(false)

const includedCandidates = computed(() => candidates.value.filter((item) => item.status === 'INCLUDED'))

onMounted(() => void refresh())

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [itemPage, candidatePage] = await Promise.all([
      service.listAdmin({
        ...(selectedLabel.value === '' ? {} : { label: selectedLabel.value }),
        ...(selectedStatus.value === '' ? {} : { status: selectedStatus.value }),
        ...(selectedStage.value === '' ? {} : { usageStage: selectedStage.value }),
      }),
      service.listCandidates(),
    ])
    items.value = itemPage.items
    candidates.value = candidatePage.items
    adminNextCursor.value = itemPage.nextCursor
    candidateNextCursor.value = candidatePage.nextCursor
    selectedCandidateIds.value = selectedCandidateIds.value.filter((id) =>
      includedCandidates.value.some((item) => item.candidateId === id))
  } catch (caught) {
    error.value = apiErrorMessage(caught, '样本库暂时无法读取；请确认功能开关和管理员权限')
  } finally {
    loading.value = false
  }
}

async function loadMoreAdmin(): Promise<void> {
  if (adminNextCursor.value === undefined) return
  loading.value = true
  error.value = null
  try {
    const page = await service.listAdmin({
      cursor: adminNextCursor.value,
      ...(selectedLabel.value === '' ? {} : { label: selectedLabel.value }),
      ...(selectedStatus.value === '' ? {} : { status: selectedStatus.value }),
      ...(selectedStage.value === '' ? {} : { usageStage: selectedStage.value }),
    })
    items.value = Object.freeze([...items.value, ...page.items])
    adminNextCursor.value = page.nextCursor
  } catch (caught) {
    error.value = apiErrorMessage(caught, '检测项下一页暂时无法读取；已保留当前页面事实')
  } finally {
    loading.value = false
  }
}

async function loadMoreCandidates(): Promise<void> {
  if (candidateNextCursor.value === undefined) return
  loading.value = true
  error.value = null
  try {
    const page = await service.listCandidates(undefined, candidateNextCursor.value)
    candidates.value = Object.freeze([...candidates.value, ...page.items])
    candidateNextCursor.value = page.nextCursor
  } catch (caught) {
    error.value = apiErrorMessage(caught, '候选下一页暂时无法读取；已保留当前页面事实')
  } finally {
    loading.value = false
  }
}

async function saveFeedback(item: AdminDetectionItem): Promise<void> {
  const label = feedbackLabel.value[item.batchItemId]
  if (label === undefined || label === '') {
    error.value = '请先选择管理员反馈标签'
    return
  }
  savingItemId.value = item.batchItemId
  error.value = null
  try {
    const feedback = await service.saveFeedback(
      item.batchItemId,
      label,
      feedbackNote.value[item.batchItemId],
      item.latestAdminFeedback?.feedbackId,
    )
    items.value = items.value.map((candidate) => candidate.batchItemId === item.batchItemId
      ? { ...candidate, latestAdminFeedback: feedback }
      : candidate)
  } catch (caught) {
    error.value = apiErrorMessage(caught, '管理员反馈未保存；后端未确认的事实不会由页面伪造')
  } finally {
    savingItemId.value = null
  }
}

async function createCandidate(item: AdminDetectionItem): Promise<void> {
  const feedback = item.latestAdminFeedback
  if (feedback === undefined) {
    error.value = '请先提交管理员反馈，再建立样本候选'
    return
  }
  savingItemId.value = item.batchItemId
  error.value = null
  try {
    const candidate = await service.createCandidate(item.batchItemId, feedback.feedbackId)
    candidates.value = Object.freeze([
      ...candidates.value.filter((value) => value.candidateId !== candidate.candidateId),
      candidate,
    ])
  } catch (caught) {
    error.value = apiErrorMessage(caught, '样本候选未建立；重复或过期事实由后端拒绝')
  } finally {
    savingItemId.value = null
  }
}

async function decide(candidate: SampleCandidate, decision: CandidateDecision): Promise<void> {
  decidingCandidateId.value = candidate.candidateId
  error.value = null
  try {
    const updated = await service.decideCandidate(
      candidate.candidateId,
      decision,
      undefined,
      candidate.latestDecisionId,
    )
    candidates.value = Object.freeze(candidates.value.map((value) =>
      value.candidateId === updated.candidateId ? updated : value))
    if (decision === 'EXCLUDE') {
      selectedCandidateIds.value = selectedCandidateIds.value.filter((id) => id !== candidate.candidateId)
    }
  } catch (caught) {
    error.value = apiErrorMessage(caught, '候选决策未保存；请以服务端返回状态为准')
  } finally {
    decidingCandidateId.value = null
  }
}

function toggleCandidate(candidateId: string, checked: boolean): void {
  selectedCandidateIds.value = checked
    ? [...new Set([...selectedCandidateIds.value, candidateId])]
    : selectedCandidateIds.value.filter((id) => id !== candidateId)
}

async function createExport(): Promise<void> {
  if (selectedCandidateIds.value.length === 0) {
    error.value = '请先选择已纳入的样本候选'
    return
  }
  loading.value = true
  error.value = null
  downloadUrl.value = null
  try {
    exportJob.value = await service.createExport(selectedCandidateIds.value, {
      ...(selectedLabel.value === '' ? {} : { label: selectedLabel.value }),
      ...(selectedStatus.value === '' ? {} : { status: selectedStatus.value }),
      ...(selectedStage.value === '' ? {} : { usage_stage: selectedStage.value }),
    })
  } catch (caught) {
    error.value = apiErrorMessage(caught, '导出请求未接受；没有生成可下载对象')
  } finally {
    loading.value = false
  }
}

async function refreshExport(): Promise<void> {
  if (exportJob.value === null) return
  loading.value = true
  error.value = null
  try {
    exportJob.value = await service.getExport(exportJob.value.jobId)
  } catch (caught) {
    error.value = apiErrorMessage(caught, '导出状态暂时无法读取')
  } finally {
    loading.value = false
  }
}

async function issueDownload(): Promise<void> {
  if (exportJob.value === null) return
  loading.value = true
  error.value = null
  try {
    downloadUrl.value = (await service.issueDownloadTicket(exportJob.value.jobId)).downloadUrl
  } catch (caught) {
    error.value = apiErrorMessage(caught, '当前导出尚无可下载对象或票据已被拒绝')
  } finally {
    loading.value = false
  }
}

async function recordReceipt(): Promise<void> {
  if (exportJob.value === null || receiptReceiver.value.trim() === '') {
    error.value = '请填写外部接收方名称'
    return
  }
  recordingReceipt.value = true
  error.value = null
  try {
    const receipt = await service.recordExternalReceipt(
      exportJob.value.jobId,
      receiptReceiver.value,
      receiptReference.value,
      receiptNote.value,
    )
    exportJob.value = Object.freeze({
      ...exportJob.value,
      externalReceipts: Object.freeze([
        ...exportJob.value.externalReceipts.filter((item) => item.receiptId !== receipt.receiptId),
        receipt,
      ]),
    })
    receiptReceiver.value = ''
    receiptReference.value = ''
    receiptNote.value = ''
  } catch (caught) {
    error.value = apiErrorMessage(caught, '外部接收回执未登记；请以服务端返回事实为准')
  } finally {
    recordingReceipt.value = false
  }
}

function labelText(label: string): string {
  const labels: Record<string, string> = {
    CORRECT_DETECTION: '正确检出',
    FALSE_POSITIVE: '误报',
    FALSE_NEGATIVE: '漏报',
    LOCALIZATION_INACCURATE: '定位不准',
    IMAGE_UNUSABLE: '图片不可用',
    UNCONFIRMED: '无法确认',
  }
  return labels[label] ?? label
}

function statusText(status: string): string {
  const statuses: Record<string, string> = {
    PENDING: '待处理', INCLUDED: '已纳入', EXCLUDED: '已排除', EXPORTED: '已导出',
    QUEUED: '排队中', PROCESSING: '处理中', SUCCEEDED: '已完成', FAILED: '有失败项',
  }
  return statuses[status] ?? status
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN') : value
}
</script>

<template>
  <section class="sample-page">
    <header class="records-heading">
      <div>
        <p class="eyebrow">R7 · 管理员样本整理</p>
        <h2>样本整理与导出</h2>
        <p class="muted">只记录管理员反馈和候选纳入/排除事实；导出异步完成，不创建数据集或训练运行。</p>
      </div>
      <button type="button" class="secondary-button" :disabled="loading" @click="refresh">刷新</button>
    </header>

    <form class="filter-rail" aria-label="检测项筛选" @submit.prevent="refresh">
      <label>反馈标签
        <select v-model="selectedLabel">
          <option value="">全部</option>
          <option v-for="label in SAMPLE_LABELS" :key="label" :value="label">{{ labelText(label) }}</option>
        </select>
      </label>
      <label>检测状态
        <select v-model="selectedStatus">
          <option value="">全部</option>
          <option value="READY">就绪</option><option value="QUEUED">排队中</option>
          <option value="PROCESSING">处理中</option><option value="COMPLETED">已完成</option>
          <option value="QUALITY_REJECTED">质量拒绝</option><option value="FAILED">技术失败</option>
        </select>
      </label>
      <label>使用阶段
        <select v-model="selectedStage">
          <option value="">全部</option><option value="NEW_BLADE">新刀片</option>
          <option value="AFTER_ONE_WHEEL">一轮后</option><option value="AFTER_TWO_WHEELS">两轮后</option>
          <option value="AFTER_THREE_WHEELS">三轮后</option><option value="OTHER">其他</option>
          <option value="UNSPECIFIED">未指定</option>
        </select>
      </label>
      <button type="submit" class="primary-button compact" :disabled="loading">应用筛选</button>
    </form>

    <p v-if="error !== null" class="panel-error" role="alert">{{ error }}</p>
    <p v-else-if="loading && items.length === 0" class="loading-ledger" role="status">正在读取样本整理事实…</p>

    <section class="sample-panel" aria-labelledby="detection-items-title">
      <div class="section-heading"><h3 id="detection-items-title">检测项反馈</h3><span>{{ items.length }} 项</span></div>
      <div v-if="items.length === 0 && !loading" class="empty-note">当前筛选没有可整理的检测项。</div>
      <ul v-else class="sample-items">
        <li v-for="item in items" :key="item.batchItemId" class="sample-item">
          <div class="sample-item__identity">
            <strong>{{ item.batchItemId }}</strong>
            <span>{{ item.status }} · {{ item.algorithmOutcome ?? '无算法结论' }}</span>
            <small>{{ formatDate(item.createdAt) }}</small>
          </div>
          <div class="sample-item__facts">
            <span>阶段：{{ item.usageStage ?? '未提供' }}</span>
            <span>当前反馈：{{ item.latestAdminFeedback ? labelText(item.latestAdminFeedback.label) : '未反馈' }}</span>
            <span v-if="item.image.objectKey !== ''" class="object-reference">原图登记：{{ item.image.objectKey }}</span>
          </div>
          <div class="sample-item__actions">
            <select v-model="feedbackLabel[item.batchItemId]" :aria-label="`反馈标签 ${item.batchItemId}`">
              <option value="">选择反馈</option>
              <option v-for="label in SAMPLE_LABELS" :key="label" :value="label">{{ labelText(label) }}</option>
            </select>
            <input v-model="feedbackNote[item.batchItemId]" maxlength="2000" placeholder="可选说明" :aria-label="`反馈说明 ${item.batchItemId}`" />
            <button type="button" class="secondary-button compact" :disabled="savingItemId === item.batchItemId" @click="saveFeedback(item)">保存反馈</button>
            <button type="button" class="secondary-button compact" :disabled="savingItemId === item.batchItemId || item.latestAdminFeedback === undefined" @click="createCandidate(item)">建立候选</button>
          </div>
        </li>
      </ul>
      <button v-if="adminNextCursor" type="button" class="secondary-button" :disabled="loading" @click="loadMoreAdmin">加载更多检测项</button>
    </section>

    <section class="sample-panel" aria-labelledby="candidate-title">
      <div class="section-heading"><h3 id="candidate-title">样本候选</h3><span>已纳入 {{ includedCandidates.length }} 项</span></div>
      <div v-if="candidates.length === 0" class="empty-note">提交反馈并建立候选后，候选会出现在这里。</div>
      <ul v-else class="candidate-list">
        <li v-for="candidate in candidates" :key="candidate.candidateId">
          <label v-if="candidate.status === 'INCLUDED'" class="candidate-check">
            <input type="checkbox" :checked="selectedCandidateIds.includes(candidate.candidateId)" @change="toggleCandidate(candidate.candidateId, ($event.target as HTMLInputElement).checked)" />
            选择导出
          </label>
          <span class="candidate-id">{{ candidate.candidateId }}</span>
          <span class="state-stamp">{{ statusText(candidate.status) }}</span>
          <span class="muted">反馈 {{ candidate.feedbackId }}</span>
          <span class="candidate-actions">
            <button type="button" class="secondary-button compact" :disabled="decidingCandidateId === candidate.candidateId || candidate.status === 'INCLUDED'" @click="decide(candidate, 'INCLUDE')">纳入</button>
            <button type="button" class="secondary-button compact" :disabled="decidingCandidateId === candidate.candidateId || candidate.status === 'EXCLUDED'" @click="decide(candidate, 'EXCLUDE')">排除</button>
          </span>
        </li>
      </ul>
      <button v-if="candidateNextCursor" type="button" class="secondary-button" :disabled="loading" @click="loadMoreCandidates">加载更多候选</button>
      <div class="export-actions">
        <button type="button" class="primary-button" :disabled="loading || selectedCandidateIds.length === 0" @click="createExport">异步导出已选候选（{{ selectedCandidateIds.length }}）</button>
      </div>
    </section>

    <section v-if="exportJob !== null" class="sample-panel" aria-labelledby="export-title">
      <div class="section-heading"><h3 id="export-title">导出作业</h3><span>{{ statusText(exportJob.status) }}</span></div>
      <p class="muted">作业 {{ exportJob.jobId }} · 创建于 {{ formatDate(exportJob.createdAt) }}</p>
      <div class="export-summary">
        <span>候选 {{ exportJob.candidateCount }}</span><span>成功 {{ exportJob.exportedCount }}</span><span>失败 {{ exportJob.failedCount }}</span>
      </div>
      <ul v-if="exportJob.failedCandidateIds.length > 0" class="failure-list">
        <li v-for="id in exportJob.failedCandidateIds" :key="id">候选 {{ id }}：该项失败，不能按成功导出处理</li>
      </ul>
      <div class="export-actions">
        <button type="button" class="secondary-button" :disabled="loading" @click="refreshExport">刷新作业状态</button>
        <button type="button" class="primary-button" :disabled="loading || (exportJob.status !== 'SUCCEEDED' && exportJob.status !== 'FAILED')" @click="issueDownload">签发短时下载票据</button>
        <a v-if="downloadUrl !== null" class="primary-button" :href="downloadUrl" target="_blank" rel="noopener">打开下载链接</a>
      </div>
      <div class="receipt-panel">
        <div class="section-heading"><h4>外部交接回执</h4><span>{{ exportJob.externalReceipts.length }} 条</span></div>
        <p class="muted">仅由管理员手工登记；不触发外部回调、轮询、消息订阅或训练任务。</p>
        <ul v-if="exportJob.externalReceipts.length > 0" class="receipt-list">
          <li v-for="receipt in exportJob.externalReceipts" :key="receipt.receiptId">
            <strong>{{ receipt.receiverName }}</strong>
            <span v-if="receipt.externalReference">交接单号：{{ receipt.externalReference }}</span>
            <span>{{ formatDate(receipt.recordedAt) }}</span>
          </li>
        </ul>
        <form class="receipt-form" @submit.prevent="recordReceipt">
          <input v-model="receiptReceiver" maxlength="256" required placeholder="接收组织或人员名称" aria-label="外部接收方" />
          <input v-model="receiptReference" maxlength="512" placeholder="外部交接单号（可选）" aria-label="外部交接单号" />
          <input v-model="receiptNote" maxlength="2000" placeholder="接收范围或失败项说明（可选）" aria-label="回执说明" />
          <button type="submit" class="secondary-button" :disabled="recordingReceipt || loading || (exportJob.status !== 'SUCCEEDED' && exportJob.status !== 'FAILED')">登记接收回执</button>
        </form>
      </div>
    </section>

    <p class="sample-notice">导出包只用于人工交接和后续受控处理；本页面不生成数据集版本、训练运行或模型事实。</p>
  </section>
</template>

<style scoped>
.sample-page { display: grid; gap: 1rem; }
.sample-panel { display: grid; gap: 0.8rem; padding: 1.15rem; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); box-shadow: var(--shadow-soft); }
.sample-items, .candidate-list, .failure-list { display: grid; gap: 0.7rem; padding: 0; margin: 0; list-style: none; }
.sample-item { display: grid; gap: 0.75rem; padding: 0.9rem; border: 1px solid var(--line); border-radius: 10px; }
.sample-item__identity, .sample-item__facts, .sample-item__actions, .candidate-list li, .export-actions, .export-summary { display: flex; gap: 0.7rem; align-items: center; flex-wrap: wrap; }
.sample-item__identity { justify-content: space-between; }
.sample-item__identity small, .sample-item__facts, .candidate-id { color: var(--muted); font-family: var(--font-mono); font-size: 0.78rem; }
.sample-item__actions select, .sample-item__actions input { min-width: 10rem; }
.candidate-list li { justify-content: space-between; padding: 0.65rem 0; border-bottom: 1px solid var(--line); }
.candidate-check { display: flex; gap: 0.35rem; align-items: center; }
.candidate-actions { display: flex; gap: 0.4rem; }
.failure-list { color: var(--danger); font-size: 0.88rem; }
.receipt-panel { display: grid; gap: 0.65rem; padding-top: 0.85rem; border-top: 1px solid var(--line); }
.receipt-list { display: grid; gap: 0.45rem; padding: 0; margin: 0; list-style: none; color: var(--muted); font-size: 0.86rem; }
.receipt-list li { display: flex; gap: 0.65rem; flex-wrap: wrap; }
.receipt-form { display: flex; gap: 0.6rem; flex-wrap: wrap; }
.receipt-form input { min-width: 12rem; flex: 1 1 12rem; }
.export-summary span { padding: 0.45rem 0.7rem; border-radius: 8px; background: var(--surface-subtle); font-family: var(--font-mono); }
.sample-notice { color: var(--muted); font-size: 0.86rem; }
.empty-note { color: var(--muted); padding: 1rem 0; }
@media (max-width: 760px) { .candidate-list li { align-items: flex-start; flex-direction: column; } .sample-item__actions { align-items: stretch; flex-direction: column; } .sample-item__actions select, .sample-item__actions input { width: 100%; } }
</style>
