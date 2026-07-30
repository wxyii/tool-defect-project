<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import type { ReviewStatus, ReviewTaskPage } from '@/api/generated'
import { useApplicationApiClient } from '@/api/runtime'
import { projectLease } from '@/features/reviews/lease'
import { ReviewService } from '@/features/reviews/service'

const router = useRouter()
const service = new ReviewService(useApplicationApiClient())
const page = ref<ReviewTaskPage | null>(null)
const status = ref<'' | ReviewStatus>('PENDING')
const loading = ref(false)
const error = ref<string | null>(null)
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
  void load()
})
onUnmounted(() => {
  if (timer !== null) clearInterval(timer)
})

async function load(cursor?: string): Promise<void> {
  loading.value = true
  error.value = null
  try {
    page.value = await service.list({
      pageSize: 25,
      ...(cursor === undefined ? {} : { cursor }),
      ...(status.value === '' ? {} : { status: status.value }),
    })
  } catch {
    error.value = '复核任务池暂时无法读取'
  } finally {
    loading.value = false
  }
}

function statusLabel(value: ReviewStatus): string {
  if (value === 'PENDING') return '等待首审'
  if (value === 'CLAIMED') return '租约占用'
  if (value === 'SECOND_REVIEW_PENDING') return '等待独立二审'
  if (value === 'ESCALATED') return '等待质量裁决'
  if (value === 'RESOLVED') return '已闭合'
  return '已取消'
}

function open(reviewTaskId: string): void {
  void router.push({ name: 'review-workbench', params: { id: reviewTaskId } })
}
</script>

<template>
  <section class="records-page review-queue">
    <header class="records-heading">
      <div>
        <p class="eyebrow">数据范围强制 · 乐观锁 · 短租约</p>
        <h2>人工复核池</h2>
        <p class="muted">
          优先级由后端事实排序；第二复核人在提交前看不到第一复核结论。
        </p>
      </div>
      <span class="records-count">{{ page?.items.length ?? 0 }} 条当前页任务</span>
    </header>

    <form class="review-filter" aria-label="复核任务筛选" @submit.prevent="load()">
      <label>
        任务阶段
        <select v-model="status">
          <option value="">全部</option>
          <option value="PENDING">等待首审</option>
          <option value="CLAIMED">已认领</option>
          <option value="SECOND_REVIEW_PENDING">等待二审</option>
          <option value="ESCALATED">等待裁决</option>
          <option value="RESOLVED">已闭合</option>
        </select>
      </label>
      <button type="submit" class="primary-button compact">刷新任务池</button>
    </form>

    <p v-if="error !== null" class="panel-error" role="alert">{{ error }}</p>
    <div v-else-if="loading" class="loading-ledger" role="status">
      正在回收过期租约并读取任务…
    </div>
    <div v-else-if="page?.items.length === 0" class="loading-ledger">
      当前范围内没有匹配任务
    </div>
    <ol v-else class="review-ledger">
      <li v-for="task in page?.items ?? []" :key="task.review_task_id">
        <button type="button" class="review-row" @click="open(task.review_task_id)">
          <span class="priority-seal" :data-priority="task.priority">
            {{ task.priority }}
          </span>
          <span>
            <strong>复核 {{ task.review_task_id.slice(0, 8) }}</strong>
            <small>采集 {{ task.capture_id.slice(0, 8) }}</small>
          </span>
          <span>
            <strong>{{ statusLabel(task.status) }}</strong>
            <small>资源版本 {{ task.record_version }}</small>
          </span>
          <span
            class="lease-cell"
            :data-expired="projectLease(task, now).expired"
          >
            <strong>{{ projectLease(task, now).label }}</strong>
            <small>{{ task.status === 'CLAIMED' ? '剩余租约' : '可进入查看' }}</small>
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
        @click="page?.next_cursor && load(page.next_cursor)"
      >
        下一页
      </button>
    </footer>
  </section>
</template>
