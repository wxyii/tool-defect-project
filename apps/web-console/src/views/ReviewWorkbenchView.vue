<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/errors'
import type {
  BusinessDisposition,
  ImageReference,
  ReviewStatus,
  ReviewSubmissionRequest,
  ReviewWorkspace,
} from '@/api/generated'
import { useApplicationApiClient } from '@/api/runtime'
import MaskWorkbench from '@/components/image-workbench/MaskWorkbench.vue'
import { MaskDraftStore } from '@/components/image-workbench/mask-history'
import { DetectionService } from '@/features/detections/service'
import { ImageTicketLoader } from '@/features/detections/image-tickets'
import { projectLease } from '@/features/reviews/lease'
import { ReviewService } from '@/features/reviews/service'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const api = useApplicationApiClient()
const reviews = new ReviewService(api)
const imageTickets = new ImageTicketLoader(new DetectionService(api))
const auth = useAuthStore()
const workspace = ref<ReviewWorkspace | null>(null)
const loading = ref(true)
const busy = ref(false)
const uploadState = ref<'IDLE' | 'UPLOADING' | 'AVAILABLE' | 'FAILED'>('IDLE')
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const sourceUrl = ref<string | null>(null)
const overlayUrl = ref<string | null>(null)
const sourceReady = ref(false)
const now = ref(Date.now())
const claimedPhase = ref<ReviewStatus | null>(null)
const annotationImageId = ref<string | null>(null)
const form = reactive({
  decision: 'HOLD' as BusinessDisposition,
  reasonCode: 'STANDARD_AMBIGUOUS',
  comment: '',
  defectCodes: '',
})
let timer: ReturnType<typeof setInterval> | null = null

const task = computed(() => workspace.value?.task ?? null)
const evidence = computed(() => workspace.value?.evidence ?? null)
const original = computed<ImageReference | undefined>(() =>
  evidence.value?.images.find((image) => image.kind === 'RAW'),
)
const overlay = computed<ImageReference | undefined>(() =>
  evidence.value?.images.find((image) =>
    image.kind === 'OVERLAY'
    || image.kind === 'DEFECT_MASK'
    || image.kind === 'HEATMAP',
  ),
)
const lease = computed(() =>
  task.value === null
    ? {
        active: false,
        expired: false,
        remainingSeconds: 0,
        label: '未认领',
      }
    : projectLease(task.value, now.value),
)
const canSubmit = computed(
  () =>
    task.value?.status === 'CLAIMED'
    && lease.value.active
    && sourceReady.value
    && auth.hasPermission('review:submit')
    && !busy.value,
)
const canAnnotate = computed(
  () => canSubmit.value && auth.hasPermission('review:annotate'),
)
const requiresComment = computed(
  () => form.reasonCode === 'OTHER' || form.reasonCode === 'STANDARD_AMBIGUOUS',
)

onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
  void load()
})
onUnmounted(() => {
  if (timer !== null) clearInterval(timer)
  imageTickets.clear()
})

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  sourceReady.value = false
  sourceUrl.value = null
  overlayUrl.value = null
  try {
    const reviewTaskId = String(route.params.id ?? '')
    workspace.value = await reviews.workspace(reviewTaskId)
    if (workspace.value.task.status !== 'CLAIMED') {
      claimedPhase.value = workspace.value.task.status
    }
    await loadImages()
  } catch {
    error.value = '复核任务不存在、越出数据范围或证据无法读取'
  } finally {
    loading.value = false
  }
}

async function loadImages(): Promise<void> {
  const raw = original.value
  if (raw === undefined) {
    error.value = '原始图像缺失，禁止形成复核结论'
    return
  }
  try {
    sourceUrl.value = await imageTickets.get(raw.image_id)
  } catch {
    error.value = '原始图像访问授权失败，禁止提交'
    return
  }
  if (overlay.value !== undefined) {
    try {
      overlayUrl.value = await imageTickets.get(overlay.value.image_id)
    } catch {
      overlayUrl.value = null
      notice.value = '模型叠加暂不可用；原图仍可独立复核'
    }
  }
}

async function claim(): Promise<void> {
  if (task.value === null) return
  busy.value = true
  error.value = null
  try {
    claimedPhase.value = task.value.status
    const claimed = await reviews.claim(task.value)
    if (workspace.value !== null) {
      workspace.value = Object.freeze({ ...workspace.value, task: claimed })
    }
    notice.value = '任务已认领；请在租约到期前提交或主动释放'
  } catch (caught) {
    await handleWriteError(caught, '任务认领失败')
  } finally {
    busy.value = false
  }
}

async function release(): Promise<void> {
  if (task.value === null) return
  busy.value = true
  try {
    const released = await reviews.release(task.value, '用户主动释放未完成复核')
    if (workspace.value !== null) {
      workspace.value = Object.freeze({ ...workspace.value, task: released })
    }
    void router.push({ name: 'reviews' })
  } catch (caught) {
    await handleWriteError(caught, '任务释放失败')
  } finally {
    busy.value = false
  }
}

async function useMask(blob: Blob): Promise<void> {
  if (task.value === null || original.value === undefined || !canAnnotate.value) {
    return
  }
  busy.value = true
  uploadState.value = 'UPLOADING'
  error.value = null
  try {
    const issued = await reviews.createMaskTicket(
      task.value,
      blob,
      original.value.width,
      original.value.height,
    )
    const receipt = await reviews.uploadMask(issued.ticket, blob)
    const completed = await reviews.completeMask(
      task.value,
      issued.ticket,
      blob,
      issued.sha256,
      receipt,
    )
    annotationImageId.value = completed.image_id
    uploadState.value = 'AVAILABLE'
    notice.value = '人工掩膜已完成服务端尺寸、通道、值域和摘要校验'
  } catch (caught) {
    uploadState.value = 'FAILED'
    await handleWriteError(caught, '人工掩膜上传或校验失败')
  } finally {
    busy.value = false
  }
}

async function submit(): Promise<void> {
  if (task.value === null || !canSubmit.value) return
  if (requiresComment.value && form.comment.trim() === '') {
    error.value = '该原因码要求填写复核说明'
    return
  }
  busy.value = true
  error.value = null
  try {
    const request: ReviewSubmissionRequest = {
      decision: form.decision,
      reason_code: form.reasonCode,
      comment: form.comment.trim(),
      defect_type_codes: form.defectCodes
        .split(',')
        .map((value) => value.trim())
        .filter((value) => value !== ''),
      annotation_image_id: annotationImageId.value as
        | ReviewSubmissionRequest['annotation_image_id'],
      client_submitted_at: new Date().toISOString() as `${string}Z`,
    }
    const response = await reviews.submit(task.value, request)
    new MaskDraftStore(window.localStorage).clear(task.value.review_task_id)
    notice.value = response.task_status === 'SECOND_REVIEW_PENDING'
      ? '首审记录已不可变保存，任务已进入独立二审'
      : response.task_status === 'ESCALATED'
        ? '两位复核结论不一致，任务已进入质量裁决并保持 HOLD'
        : `复核已闭合，后端最终处置：${response.business_disposition}`
    await load()
  } catch (caught) {
    await handleWriteError(caught, '复核提交失败')
  } finally {
    busy.value = false
  }
}

async function handleWriteError(caught: unknown, fallback: string): Promise<void> {
  if (caught instanceof ApiError && caught.status === 409) {
    error.value = '任务版本或租约已变化，已重新读取服务端事实；本地草稿仍保留'
    await load()
    return
  }
  error.value = caught instanceof ApiError ? caught.message : fallback
}

function algorithmLabel(): string {
  const outcome = evidence.value?.detection.algorithm_outcome
  if (outcome === 'QUALIFIED') return '算法倾向：合格'
  if (outcome === 'UNQUALIFIED') return '算法倾向：不合格'
  return '算法无法定案或尚无结论'
}
</script>

<template>
  <section v-if="loading" class="loading-ledger" role="status">
    正在核对复核任务与受控证据…
  </section>
  <section v-else-if="workspace !== null" class="review-workbench-page">
    <header class="review-workbench-heading">
      <div>
        <RouterLink to="/reviews" class="back-link">← 返回复核任务池</RouterLink>
        <p class="eyebrow">
          质量裁决桌 / {{ workspace.task.review_task_id.slice(0, 8) }}
        </p>
        <h2>采集 {{ workspace.task.capture_id.slice(0, 8) }}</h2>
        <p class="muted">
          {{ algorithmLabel() }} · 模型版本
          {{ workspace.evidence.detection.model_version ?? '未提供' }}
        </p>
      </div>
      <div class="lease-card" :data-expired="lease.expired">
        <small>任务状态 {{ workspace.task.status }}</small>
        <strong>{{ lease.label }}</strong>
        <span>{{ lease.active ? '认领租约剩余' : '当前不可提交' }}</span>
      </div>
    </header>

    <p
      v-if="claimedPhase === 'SECOND_REVIEW_PENDING'"
      class="blind-review-note"
      role="status"
    >
      独立二审模式：服务端未返回第一复核人的结论或人工掩膜。
    </p>
    <p v-if="notice !== null" class="panel-notice" role="status">{{ notice }}</p>
    <p v-if="error !== null" class="panel-error" role="alert">{{ error }}</p>

    <div
      v-if="workspace.task.status !== 'CLAIMED'
        && workspace.task.status !== 'RESOLVED'
        && workspace.task.status !== 'CANCELLED'"
      class="claim-gate"
    >
      <div>
        <strong>认领后开始形成复核记录</strong>
        <p>认领使用资源版本与短租约；并发认领只有一个请求会成功。</p>
      </div>
      <button
        type="button"
        class="primary-button compact"
        :disabled="busy || !auth.hasPermission('review:claim')"
        @click="claim"
      >
        认领此任务
      </button>
    </div>

    <div v-if="sourceUrl !== null && original !== undefined" class="review-workbench-grid">
      <MaskWorkbench
        :review-task-id="workspace.task.review_task_id"
        :source-url="sourceUrl"
        :overlay-url="overlayUrl"
        :width="original.width"
        :height="original.height"
        @source-ready="sourceReady = true"
        @source-error="sourceReady = false; error = '原始图像解码失败，禁止提交'"
        @mask-ready="useMask"
      />

      <aside class="review-decision-panel" aria-labelledby="decision-title">
        <div>
          <p class="eyebrow">不可变提交</p>
          <h3 id="decision-title">复核结论</h3>
        </div>
        <fieldset>
          <legend>最终建议</legend>
          <label><input v-model="form.decision" type="radio" value="PASS" /> ✓ 通过</label>
          <label><input v-model="form.decision" type="radio" value="FAIL" /> × 不通过</label>
          <label><input v-model="form.decision" type="radio" value="HOLD" /> ! 暂停等待</label>
        </fieldset>
        <label>
          原因码
          <select v-model="form.reasonCode">
            <option value="CONFIRMED_CORRECT">抽检确认算法正确</option>
            <option value="MODEL_FALSE_POSITIVE">模型误报</option>
            <option value="MODEL_FALSE_NEGATIVE">模型漏检</option>
            <option value="MASK_INACCURATE">模型掩膜不准确</option>
            <option value="IMAGE_QUALITY">图片质量问题</option>
            <option value="PREPROCESS_FAILURE">预处理失败</option>
            <option value="DEVICE_OR_PROCESS">设备或工艺异常</option>
            <option value="STANDARD_AMBIGUOUS">判定标准有争议</option>
            <option value="OTHER">其他</option>
          </select>
        </label>
        <label>
          缺陷类型编码
          <input
            v-model="form.defectCodes"
            maxlength="512"
            placeholder="多个编码以英文逗号分隔"
          />
        </label>
        <label>
          复核说明
          <textarea
            v-model="form.comment"
            maxlength="2000"
            :required="requiresComment"
            rows="5"
          />
        </label>
        <div class="annotation-state" :data-state="uploadState">
          <strong>人工掩膜：{{ uploadState }}</strong>
          <small v-if="annotationImageId !== null">
            已验证对象 {{ annotationImageId.slice(0, 8) }}
          </small>
          <small v-else>可选；提交只引用服务端已验证对象</small>
        </div>
        <button
          type="button"
          class="primary-button"
          :disabled="!canSubmit"
          @click="submit"
        >
          提交不可变复核记录
        </button>
        <button
          v-if="workspace.task.status === 'CLAIMED'"
          type="button"
          class="text-button release-action"
          :disabled="busy"
          @click="release"
        >
          释放任务并返回任务池
        </button>
        <p class="decision-caveat">
          页面不根据算法概率计算最终处置；冲突由后端进入 HOLD 或质量裁决。
        </p>
      </aside>
    </div>
  </section>
  <section v-else class="panel-error" role="alert">
    {{ error ?? '复核工作区无法打开' }}
  </section>
</template>
