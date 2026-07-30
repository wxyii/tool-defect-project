<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { useApplicationApiClient } from '@/api/runtime'
import DispositionStatus from '@/components/DispositionStatus.vue'
import { DetectionService } from '@/features/detections/service'
import type { WorkstationSnapshot } from '@/features/workstation/projection'
import { WorkstationService } from '@/features/workstation/service'

const props = defineProps<{
  initialSnapshot?: WorkstationSnapshot
}>()

const service =
  props.initialSnapshot === undefined
    ? new WorkstationService(
        new DetectionService(useApplicationApiClient()),
      )
    : null
const snapshot = ref<WorkstationSnapshot>(
  props.initialSnapshot ?? service?.snapshot ?? {
    connection: 'OFFLINE',
    current: null,
    recent: [],
    lastSynchronizedAt: null,
    edge: {
      queueDepth: null,
      oldestTaskAgeSeconds: null,
      diskUsageRatio: null,
    },
  },
)
let poller: ReturnType<typeof setInterval> | null = null

const current = computed(() => snapshot.value.current)
const connectionText = computed(() =>
  snapshot.value.connection === 'ONLINE'
    ? '中心在线'
    : '中心离线，采集客户端正在本地排队',
)
const stageText = computed(() => {
  const stage = current.value?.capture.capture_status
  const labels = {
    CREATED: '采集已登记',
    UPLOADING: '原图上传中',
    READY: '等待提交检测',
    SUBMITTED: '已进入检测队列',
    PROCESSING: '推理执行中',
    REVIEW_PENDING: '等待人工复核',
    FINALIZED: '中心已最终定案',
    FAILED: '技术失败，等待处理',
  } as const
  return stage === undefined ? '等待首条采集事实' : labels[stage]
})

onMounted(() => {
  if (props.initialSnapshot !== undefined) return
  void refresh()
  poller = setInterval(() => void refresh(), 5_000)
})

onBeforeUnmount(() => {
  if (poller !== null) clearInterval(poller)
})

async function refresh(): Promise<void> {
  if (service === null) return
  try {
    snapshot.value = await service.refresh()
  } catch {
    snapshot.value = service.snapshot
  }
}

function metric(value: number | null, suffix = ''): string {
  return value === null ? '未上报' : `${value}${suffix}`
}
</script>

<template>
  <section class="workstation-grid" aria-label="工位实时状态">
    <header
      class="workstation-strip"
      :data-connection="snapshot.connection"
      role="status"
    >
      <span class="connection-glyph" aria-hidden="true">
        {{ snapshot.connection === 'ONLINE' ? '●' : '◌' }}
      </span>
      <strong>{{ connectionText }}</strong>
      <span>
        最近同步
        {{
          snapshot.lastSynchronizedAt === null
            ? '尚无'
            : new Date(snapshot.lastSynchronizedAt).toLocaleTimeString('zh-CN')
        }}
      </span>
    </header>

    <article class="hero-card workstation-hero">
      <div>
        <p class="eyebrow">当前刀具 / 后端事实</p>
        <h2>{{ stageText }}</h2>
        <p v-if="current !== null" class="capture-code">
          CAPTURE—{{ current.capture.capture_id.slice(0, 8) }}
        </p>
        <p class="muted">
          {{
            current === null
              ? '页面只读取中央结果，不会影响后台采集服务。'
              : `任务 ${current.detection.detection_task_id.slice(0, 8)} · ${current.detection.model_version ?? '版本锁定中'}`
          }}
        </p>
      </div>
      <DispositionStatus
        v-if="current?.capture.business_disposition != null"
        :disposition="current.capture.business_disposition"
      />
      <div v-else class="pending-disposition" role="status">
        <strong>未形成最终处置</strong>
        <small>不根据算法结论推测生产动作</small>
      </div>
    </article>

    <article class="metric-card">
      <span>本地待上传</span>
      <strong>{{ metric(snapshot.edge.queueDepth) }}</strong>
      <small>采集代理独立运行；无上报时不猜测为 0</small>
    </article>
    <article class="metric-card">
      <span>最老任务年龄</span>
      <strong>{{ metric(snapshot.edge.oldestTaskAgeSeconds, ' 秒') }}</strong>
      <small>断线时保持最近中央事实，不回退状态</small>
    </article>
    <article class="metric-card">
      <span>磁盘使用率</span>
      <strong>
        {{
          snapshot.edge.diskUsageRatio === null
            ? '未上报'
            : `${(snapshot.edge.diskUsageRatio * 100).toFixed(0)}%`
        }}
      </strong>
      <small>95% 水位由采集代理直接暂停新采集</small>
    </article>

    <article class="timeline-card">
      <div class="section-heading">
        <div>
          <p class="eyebrow">最近记录</p>
          <h3>中央检测流水</h3>
        </div>
        <RouterLink to="/detections" class="text-button">查看全部 →</RouterLink>
      </div>
      <ol class="recent-runs">
        <li
          v-for="item in snapshot.recent"
          :key="item.detection_task_id"
        >
          <RouterLink
            :to="{
              name: 'detection-detail',
              params: { id: item.detection_task_id },
            }"
          >
            <strong>{{ item.detection_task_id.slice(0, 8) }}</strong>
            <span>{{ item.task_status }}</span>
            <small>
              {{
                item.algorithm_outcome == null
                  ? '算法尚无结果'
                  : `算法 ${item.algorithm_outcome}`
              }}
            </small>
          </RouterLink>
        </li>
        <li v-if="snapshot.recent.length === 0" class="empty-run">
          暂无中央检测记录
        </li>
      </ol>
    </article>
  </section>
</template>
