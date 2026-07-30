<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import type { DetectionDetail, ImageReference, JsonObject } from '@/api/generated'
import { useApplicationApiClient } from '@/api/runtime'
import DispositionStatus from '@/components/DispositionStatus.vue'
import EvidenceImage from '@/components/EvidenceImage.vue'
import { DetectionService } from '@/features/detections/service'

const route = useRoute()
const service = new DetectionService(useApplicationApiClient())
const detail = ref<DetectionDetail | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)

const preview = computed<ImageReference | undefined>(() =>
  detail.value?.images.find((image) => image.kind === 'THUMBNAIL'),
)
const evidence = computed(() =>
  detail.value?.images.filter((image) => image.kind !== 'THUMBNAIL') ?? [],
)

onMounted(async () => {
  const identifier = String(route.params.id ?? '')
  try {
    detail.value = await service.get(identifier)
  } catch {
    error.value = '检测详情不存在或不在当前数据权限范围'
  } finally {
    loading.value = false
  }
})

function safeAttempt(value: JsonObject): readonly [string, string][] {
  return safeEntries(value, [
    'attempt_no',
    'status',
    'worker_id',
    'error_code',
    'started_at',
    'finished_at',
  ])
}

function safeDisposition(value: JsonObject): readonly [string, string][] {
  return safeEntries(value, [
    'disposition',
    'reason_code',
    'policy_version',
    'occurred_at',
  ])
}

function safeVersions(value: JsonObject): readonly [string, string][] {
  return safeEntries(value, [
    'pipeline_version',
    'model_version',
    'preprocessor_version',
    'algorithm_version',
    'policy_version',
  ])
}

function safeEntries(
  value: JsonObject,
  allowed: readonly string[],
): readonly [string, string][] {
  return Object.entries(value)
    .filter(([key, item]) => allowed.includes(key) && isScalar(item))
    .map(([key, item]) => [key, item === null ? '—' : String(item)])
}

function isScalar(value: unknown): value is string | number | boolean | null {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value)
}
</script>

<template>
  <section v-if="loading" class="loading-ledger" role="status">正在核对检测事实…</section>
  <section v-else-if="error !== null" class="panel-error" role="alert">{{ error }}</section>
  <section v-else-if="detail !== null" class="detail-page">
    <header class="detail-heading">
      <div>
        <RouterLink to="/detections" class="back-link">← 返回检测记录</RouterLink>
        <p class="eyebrow">检测事实 / {{ detail.detection.detection_task_id.slice(0, 8) }}</p>
        <h2>{{ detail.capture.capture_id.slice(0, 8) }}</h2>
        <p class="muted">
          中央状态 {{ detail.capture.capture_status }} · 执行状态
          {{ detail.detection.task_status }}
        </p>
      </div>
      <DispositionStatus
        v-if="detail.capture.business_disposition !== null"
        :disposition="detail.capture.business_disposition"
      />
      <div v-else class="pending-disposition" role="status">
        <strong>尚未形成最终处置</strong>
        <small>页面不根据算法分数自行定案</small>
      </div>
    </header>

    <section class="detail-section" aria-labelledby="evidence-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">按需授权 · 分级加载</p>
          <h3 id="evidence-title">图像证据</h3>
        </div>
        <span>{{ evidence.length }} 项</span>
      </div>
      <div class="evidence-grid">
        <EvidenceImage
          v-for="image in evidence"
          :key="image.image_id"
          :image="image"
          :preview="preview"
        />
      </div>
    </section>

    <div class="detail-columns">
      <section class="detail-section">
        <div class="section-heading">
          <h3>执行尝试</h3>
          <span>{{ detail.attempts.length }}</span>
        </div>
        <ol class="fact-list">
          <li v-for="(attempt, index) in detail.attempts" :key="index">
            <strong>尝试 {{ index + 1 }}</strong>
            <dl>
              <template v-for="[key, value] in safeAttempt(attempt)" :key="key">
                <dt>{{ key }}</dt><dd>{{ value }}</dd>
              </template>
            </dl>
          </li>
        </ol>
      </section>

      <section class="detail-section">
        <div class="section-heading">
          <h3>处置历史</h3>
          <span>{{ detail.disposition_history.length }}</span>
        </div>
        <ol class="fact-list">
          <li
            v-for="(disposition, index) in detail.disposition_history"
            :key="index"
          >
            <strong>处置事实 {{ index + 1 }}</strong>
            <dl>
              <template
                v-for="[key, value] in safeDisposition(disposition)"
                :key="key"
              >
                <dt>{{ key }}</dt><dd>{{ value }}</dd>
              </template>
            </dl>
          </li>
        </ol>
      </section>
    </div>

    <section class="detail-section">
      <div class="section-heading"><h3>锁定版本</h3></div>
      <dl class="version-grid">
        <template v-for="[key, value] in safeVersions(detail.versions)" :key="key">
          <dt>{{ key }}</dt><dd>{{ value }}</dd>
        </template>
      </dl>
    </section>
  </section>
</template>
