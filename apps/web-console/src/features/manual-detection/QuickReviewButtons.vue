<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { QuickReviewDecision } from '@/api/generated'

const props = defineProps<{
  current?: QuickReviewDecision
  submit: (decision: QuickReviewDecision, idempotencyKey: string) => Promise<void>
}>()
const saving = ref<QuickReviewDecision | null>(null)
const saved = ref<QuickReviewDecision | undefined>(props.current)
const error = ref<string | null>(null)
const keys = new Map<QuickReviewDecision, string>()

watch(() => props.current, (value) => { saved.value = value })

const status = computed(() => {
  if (saving.value !== null) return '正在保存反馈…'
  if (error.value !== null) return error.value
  if (saved.value === 'UNABLE_TO_DETERMINE') return '已保存“无法判断”，该项保持暂停等待处理'
  if (saved.value !== undefined) return '反馈已保存；再次选择会新增修订，不覆盖原记录'
  return '每次选择立即保存，不需要提交全部结果'
})

async function choose(decision: QuickReviewDecision): Promise<void> {
  if (saving.value !== null) return
  saving.value = decision
  error.value = null
  const key = keys.get(decision) ?? crypto.randomUUID()
  keys.set(decision, key)
  try {
    await props.submit(decision, key)
    saved.value = decision
    keys.delete(decision)
  } catch {
    error.value = '反馈保存失败，可重试当前选择'
  } finally {
    saving.value = null
  }
}
</script>

<template>
  <div class="quick-review" aria-label="逐图快速反馈">
    <div class="quick-review__buttons">
      <button type="button" :aria-pressed="saved === 'DEFECT_CONFIRMED'" :disabled="saving !== null" @click="choose('DEFECT_CONFIRMED')">
        确认存在缺陷
      </button>
      <button type="button" :aria-pressed="saved === 'NO_DEFECT_CONFIRMED'" :disabled="saving !== null" @click="choose('NO_DEFECT_CONFIRMED')">
        确认无缺陷
      </button>
      <button type="button" :aria-pressed="saved === 'UNABLE_TO_DETERMINE'" :disabled="saving !== null" @click="choose('UNABLE_TO_DETERMINE')">
        无法判断
      </button>
    </div>
    <p :class="{ 'panel-error': error !== null }" :role="error === null ? 'status' : 'alert'">{{ status }}</p>
  </div>
</template>

<style scoped>
.quick-review { display: grid; gap: .55rem; }
.quick-review__buttons { display: flex; flex-wrap: wrap; gap: .5rem; }
.quick-review button { min-height: 2.5rem; padding: .55rem .8rem; border: 1px solid var(--line-strong); border-radius: .45rem; background: #fff; color: var(--ink); cursor: pointer; }
.quick-review button[aria-pressed="true"] { border-color: var(--accent-deep); background: var(--accent-soft); font-weight: 700; }
.quick-review button:disabled { cursor: wait; opacity: .65; }
.quick-review p { margin: 0; color: var(--muted); font-size: .78rem; }
</style>
