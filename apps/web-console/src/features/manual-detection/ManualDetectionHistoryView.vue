<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import type { DetectionBatch } from '@/api/generated'
import { useApplicationApiClient } from '@/api/runtime'
import { ManualDetectionService } from './service'

const service = new ManualDetectionService(useApplicationApiClient())
const items = ref<readonly DetectionBatch[]>([])
const nextCursor = ref<string | undefined>()
const status = ref('')
const source = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

const visible = computed(() => items.value.filter((item) =>
  (status.value === '' || item.status === status.value)
  && (source.value === '' || item.source === source.value),
))

onMounted(() => void load())
async function load(cursor?: string): Promise<void> {
  loading.value = true; error.value = null
  try {
    const page = await service.list(cursor)
    items.value = cursor === undefined ? page.items : Object.freeze([...items.value, ...page.items])
    nextCursor.value = page.nextCursor
  } catch { error.value = '批次历史暂时无法读取或不在当前权限范围' }
  finally { loading.value = false }
}
</script>

<template>
  <section class="manual-page">
    <header class="records-heading"><div><p class="eyebrow">本人 / 授权范围 · 游标分页</p><h2>批次历史</h2><p class="muted">列表计数和状态均来自后端批次事实。</p></div><RouterLink class="primary-button" :to="{ name: 'manual-detection-upload' }">新建手工检测</RouterLink></header>
    <form class="filter-rail" aria-label="批次历史筛选" @submit.prevent>
      <label>批次状态<select v-model="status"><option value="">全部</option><option v-for="value in ['DRAFT','UPLOADING','READY','PROCESSING','COMPLETED','PARTIALLY_COMPLETED','FAILED','CANCELLED']" :key="value" :value="value">{{ value }}</option></select></label>
      <label>来源<select v-model="source"><option value="">全部</option><option value="MANUAL_UPLOAD">手工上传</option><option value="PRODUCTION_CAPTURE">产线采集</option></select></label>
    </form>
    <p v-if="error" class="panel-error" role="alert">{{ error }}</p><p v-else-if="loading && items.length === 0" class="loading-ledger" role="status">正在读取批次…</p>
    <ol v-else class="detection-ledger">
      <li v-for="batch in visible" :key="batch.batch_id"><RouterLink class="detection-row batch-row" :to="{ name: 'manual-detection-detail', params: { id: batch.batch_id } }"><span class="detection-row__index">批</span><span><strong>{{ batch.batch_no }}</strong><small>{{ new Date(batch.created_at).toLocaleString() }}</small></span><span><strong>{{ batch.counts.total }} 张</strong><small>异常 {{ batch.counts.defect_suspected + batch.counts.inconclusive + batch.counts.quality_rejected + batch.counts.technical_failed }}</small></span><span class="state-stamp">{{ batch.status }}</span><span>→</span></RouterLink></li>
    </ol>
    <button v-if="nextCursor" type="button" class="secondary-button" :disabled="loading" @click="load(nextCursor)">加载下一页</button>
  </section>
</template>

<style scoped>
.manual-page { display: grid; gap: 1rem; }.batch-row { grid-template-columns: 2rem 2fr 1fr auto 1rem; }
@media (max-width: 720px) { .batch-row { grid-template-columns: 2rem 1fr auto; }.batch-row span:nth-child(3) { display:none; } }
</style>
