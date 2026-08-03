<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import type { DetectionBatchItem, QuickReviewDecision } from '@/api/generated'
import { useApplicationApiClient } from '@/api/runtime'
import QuickReviewButtons from './QuickReviewButtons.vue'
import { ManualDetectionService, resultPriority, type DetectionBatchDetail } from './service'

const route = useRoute()
const service = new ManualDetectionService(useApplicationApiClient())
const detail = ref<DetectionBatchDetail | null>(null)
const urls = ref<Record<string, string>>({})
const resultUrls = ref<Record<string, string>>({})
const errors = ref<Record<string, string>>({})
const error = ref<string | null>(null)
const loading = ref(true)
let timer: ReturnType<typeof setTimeout> | undefined

const terminal = computed(() => detail.value !== null && ['COMPLETED','PARTIALLY_COMPLETED','FAILED','CANCELLED'].includes(detail.value.status))
const sortedItems = computed(() => [...(detail.value?.items ?? [])].sort((left, right) => resultPriority(left) - resultPriority(right)))

onMounted(() => void refresh())
onBeforeUnmount(() => { if (timer !== undefined) clearTimeout(timer) })

async function refresh(): Promise<void> {
  if (timer !== undefined) { clearTimeout(timer); timer = undefined }
  try {
    const batchId = String(route.params.id ?? '')
    detail.value = await service.get(batchId)
    const enriched = await Promise.all(detail.value.items.map(async (item) => {
      if (['PENDING_UPLOAD','UPLOADING'].includes(item.status)) return item
      try {
        const access = await service.getItem(batchId, item.batch_item_id)
        if (access.readUrl !== undefined) urls.value = { ...urls.value, [item.batch_item_id]: access.readUrl }
        if (access.resultReadUrl !== undefined) resultUrls.value = { ...resultUrls.value, [item.batch_item_id]: access.resultReadUrl }
        if (access.errorCode !== undefined) errors.value = { ...errors.value, [item.batch_item_id]: access.errorCode }
        return access.item
      } catch { return item }
    }))
    detail.value = Object.freeze({ ...detail.value, items: Object.freeze(enriched) })
    if (!terminal.value) timer = setTimeout(() => void refresh(), 2000)
  } catch { error.value = '批次详情不存在或不在当前权限范围' }
  finally { loading.value = false }
}

async function saveReview(item: DetectionBatchItem, decision: QuickReviewDecision, key: string): Promise<void> {
  if (detail.value === null) return
  await service.quickReview(detail.value.batch_id, item.batch_item_id, decision, undefined, key)
  await refresh()
}

function itemLabel(item: DetectionBatchItem): string {
  if (item.status === 'QUALITY_REJECTED') return '图片质量异常'
  if (item.status === 'FAILED') return '技术失败'
  if (item.algorithm_outcome === 'UNQUALIFIED') return '疑似缺陷'
  if (item.algorithm_outcome === 'INCONCLUSIVE') return '不确定'
  if (item.algorithm_outcome === 'QUALIFIED') return '未发现明显缺陷'
  return '等待服务端结果'
}
</script>

<template>
  <section v-if="loading" class="loading-ledger" role="status">正在恢复批次和逐图状态…</section>
  <section v-else-if="error" class="panel-error" role="alert">{{ error }}</section>
  <section v-else-if="detail" class="manual-detail">
    <header class="detail-heading"><div><RouterLink :to="{ name: 'manual-detection-history' }" class="back-link">← 返回批次历史</RouterLink><p class="eyebrow">{{ detail.source }} · {{ detail.batch_no }}</p><h2>批次结果</h2><p class="muted">{{ detail.status }} · {{ terminal ? '处理已形成终态' : '页面正在自动刷新服务端状态' }}</p></div></header>
    <dl class="count-grid" aria-label="批次结果计数"><div><dt>总数</dt><dd>{{ detail.counts.total }}</dd></div><div><dt>疑似缺陷</dt><dd>{{ detail.counts.defect_suspected }}</dd></div><div><dt>未发现明显缺陷</dt><dd>{{ detail.counts.normal }}</dd></div><div><dt>不确定</dt><dd>{{ detail.counts.inconclusive }}</dd></div><div><dt>图片质量异常</dt><dd>{{ detail.counts.quality_rejected }}</dd></div><div><dt>技术失败</dt><dd>{{ detail.counts.technical_failed }}</dd></div></dl>
    <p v-if="detail.counts.completed < detail.counts.total" role="status" class="loading-ledger">已完成 {{ detail.counts.completed }} / {{ detail.counts.total }}，中间处理无需人工确认。</p>
    <ol class="result-grid">
      <li v-for="item in sortedItems" :key="item.batch_item_id" :data-priority="resultPriority(item)"><div class="result-image"><img v-if="urls[item.batch_item_id]" :src="urls[item.batch_item_id]" :alt="`图片项 ${item.batch_item_id.slice(0,8)} 原图`" /><span v-else>受控图片暂不可读</span></div><div><strong>{{ itemLabel(item) }}</strong><p>{{ item.status }} · {{ item.batch_item_id.slice(0, 8) }}</p><p v-if="item.status === 'QUALITY_REJECTED'">请重新拍摄或上传；该项未进入正常缺陷推理。</p><p v-if="errors[item.batch_item_id]" class="panel-error">错误码：{{ errors[item.batch_item_id] }}</p><a v-if="resultUrls[item.batch_item_id]" :href="resultUrls[item.batch_item_id]" target="_blank" rel="noopener noreferrer">打开派生结果</a><details v-if="item.quality"><summary>质量检查 · {{ item.quality.overall }}</summary><ul><li v-for="check in item.quality.checks" :key="check.check_type">{{ check.check_type }}：{{ check.status }} · {{ check.user_hint }}</li></ul></details></div><QuickReviewButtons :current="item.quick_review_decision" :submit="(decision, key) => saveReview(item, decision, key)" /></li>
    </ol>
  </section>
</template>

<style scoped>
.manual-detail { display:grid; gap:1rem; }.count-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(125px,1fr)); gap:.65rem; margin:0; }.count-grid div { padding:.8rem; border:1px solid var(--line); border-radius:.55rem; background:var(--panel); }.count-grid dt { color:var(--muted); }.count-grid dd { margin:.2rem 0 0; font-size:1.45rem; font-weight:800; }.result-grid { display:grid; gap:.8rem; padding:0; list-style:none; }.result-grid li { display:grid; grid-template-columns:140px minmax(150px,1fr) minmax(260px,1.4fr); gap:1rem; align-items:center; padding:.9rem; border:1px solid var(--line); border-left:5px solid var(--success); border-radius:.6rem; background:var(--panel); }.result-grid li[data-priority="0"] { border-left-color:var(--danger); }.result-grid li[data-priority="1"],.result-grid li[data-priority="2"] { border-left-color:var(--warning); }.result-image { display:grid; place-items:center; min-height:100px; background:var(--well); color:var(--muted); }.result-image img { width:100%; max-height:120px; object-fit:contain; }@media(max-width:800px){.result-grid li{grid-template-columns:1fr}.result-image{max-width:240px}}
.result-grid li[data-priority="3"] .result-image { max-width:80px; min-height:60px; }.result-grid li[data-priority="3"] .result-image img { max-height:60px; }
</style>
