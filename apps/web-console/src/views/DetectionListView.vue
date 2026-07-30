<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type {
  AlgorithmOutcome,
  BusinessDisposition,
  DetectionPage,
} from '@/api/generated'
import { useApplicationApiClient } from '@/api/runtime'
import {
  DetectionService,
  type DetectionFilters,
} from '@/features/detections/service'

const route = useRoute()
const router = useRouter()
const service = new DetectionService(useApplicationApiClient())
const page = ref<DetectionPage | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const filters = reactive({
  businessDisposition: queryDisposition(route.query.business_disposition),
  algorithmOutcome: queryOutcome(route.query.algorithm_outcome),
  modelVersion:
    typeof route.query.model_version === 'string' ? route.query.model_version : '',
})

const hasFilters = computed(
  () =>
    filters.businessDisposition !== ''
    || filters.algorithmOutcome !== ''
    || filters.modelVersion.trim() !== '',
)

onMounted(() => void load())
watch(
  () => [
    filters.businessDisposition,
    filters.algorithmOutcome,
    filters.modelVersion,
  ],
  () => {
    void router.replace({
      query: {
        ...(filters.businessDisposition === ''
          ? {}
          : { business_disposition: filters.businessDisposition }),
        ...(filters.algorithmOutcome === ''
          ? {}
          : { algorithm_outcome: filters.algorithmOutcome }),
        ...(filters.modelVersion.trim() === ''
          ? {}
          : { model_version: filters.modelVersion.trim() }),
      },
    })
  },
)

async function load(cursor?: string): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const request: DetectionFilters = {
      pageSize: 25,
      ...(cursor === undefined ? {} : { cursor }),
      ...(filters.businessDisposition === ''
        ? {}
        : {
            businessDisposition:
              filters.businessDisposition as BusinessDisposition,
          }),
      ...(filters.algorithmOutcome === ''
        ? {}
        : {
            algorithmOutcome: filters.algorithmOutcome as AlgorithmOutcome,
          }),
      ...(filters.modelVersion.trim() === ''
        ? {}
        : { modelVersion: filters.modelVersion.trim() }),
    }
    page.value = await service.list(request)
  } catch {
    error.value = '检测记录暂时无法读取'
  } finally {
    loading.value = false
  }
}

function clearFilters(): void {
  filters.businessDisposition = ''
  filters.algorithmOutcome = ''
  filters.modelVersion = ''
  void load()
}

function queryDisposition(value: unknown): '' | BusinessDisposition {
  return value === 'PASS' || value === 'FAIL' || value === 'HOLD' ? value : ''
}

function queryOutcome(value: unknown): '' | AlgorithmOutcome {
  return value === 'QUALIFIED'
    || value === 'UNQUALIFIED'
    || value === 'INCONCLUSIVE'
    ? value
    : ''
}

function outcomeLabel(value: AlgorithmOutcome | null | undefined): string {
  if (value === 'QUALIFIED') return '算法：合格倾向'
  if (value === 'UNQUALIFIED') return '算法：不合格倾向'
  if (value === 'INCONCLUSIVE') return '算法：无法定案'
  return '算法：尚无结果'
}
</script>

<template>
  <section class="records-page">
    <header class="records-heading">
      <div>
        <p class="eyebrow">游标分页 · 后端权限范围</p>
        <h2>检测记录</h2>
        <p class="muted">算法结论仅作证据，最终处置以详情中的后端事实为准。</p>
      </div>
      <span class="records-count">{{ page?.items.length ?? 0 }} 条当前页记录</span>
    </header>

    <form class="filter-rail" aria-label="检测记录筛选" @submit.prevent="load()">
      <label>
        最终处置
        <select v-model="filters.businessDisposition">
          <option value="">全部</option>
          <option value="PASS">通过</option>
          <option value="FAIL">不通过</option>
          <option value="HOLD">暂停等待</option>
        </select>
      </label>
      <label>
        算法结论
        <select v-model="filters.algorithmOutcome">
          <option value="">全部</option>
          <option value="QUALIFIED">合格倾向</option>
          <option value="UNQUALIFIED">不合格倾向</option>
          <option value="INCONCLUSIVE">无法定案</option>
        </select>
      </label>
      <label>
        模型版本
        <input v-model="filters.modelVersion" maxlength="128" placeholder="例如 model/3" />
      </label>
      <button type="submit" class="primary-button compact">应用筛选</button>
      <button
        v-if="hasFilters"
        type="button"
        class="text-button"
        @click="clearFilters"
      >
        清除
      </button>
    </form>

    <p v-if="error !== null" class="panel-error" role="alert">{{ error }}</p>
    <div v-else-if="loading" class="loading-ledger" role="status">正在读取受控记录…</div>
    <div v-else-if="page?.items.length === 0" class="loading-ledger">没有匹配记录</div>
    <ol v-else class="detection-ledger">
      <li v-for="item in page?.items ?? []" :key="item.detection_task_id">
        <RouterLink
          :to="{ name: 'detection-detail', params: { id: item.detection_task_id } }"
          class="detection-row"
        >
          <span class="detection-row__index" aria-hidden="true">DET</span>
          <span>
            <strong>{{ item.detection_task_id.slice(0, 8) }}</strong>
            <small>{{ item.model_version ?? '模型版本待锁定' }}</small>
          </span>
          <span>
            <strong>{{ outcomeLabel(item.algorithm_outcome) }}</strong>
            <small>
              {{ item.confidence == null ? '置信度未形成' : `置信度 ${(item.confidence * 100).toFixed(1)}%` }}
            </small>
          </span>
          <span class="state-stamp" :data-state="item.task_status">
            {{ item.task_status }}
          </span>
          <span aria-hidden="true">→</span>
        </RouterLink>
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
  </section>
</template>
