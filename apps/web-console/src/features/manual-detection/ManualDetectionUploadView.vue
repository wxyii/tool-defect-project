<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import type { DetectionBatchItem, UsageStage } from '@/api/generated'
import { useApplicationApiClient } from '@/api/runtime'
import { ManualDetectionService, prepareImage, type ManualDetectionCapabilities, type PreparedImage, type UploadItemIntent } from './service'

interface SelectedImage {
  readonly id: string
  readonly prepared: PreparedImage
  readonly previewUrl: string
  readonly addKey: string
  readonly completeKey: string
  intent?: UploadItemIntent
  item?: DetectionBatchItem
  state: 'READY' | 'UPLOADING' | 'UPLOADED' | 'FAILED'
  error?: string
}

const router = useRouter()
const service = new ManualDetectionService(useApplicationApiClient())
const capabilities = ref<ManualDetectionCapabilities | null>(null)
const selected = ref<SelectedImage[]>([])
const stage = ref<UsageStage>('UNSPECIFIED')
const note = ref('')
const loading = ref(true)
const submitting = ref(false)
const error = ref<string | null>(null)
const batchId = ref<string | null>(null)

onMounted(async () => {
  try { capabilities.value = await service.capabilities() }
  catch { error.value = '手工检测能力暂时无法读取' }
  finally { loading.value = false }
})
onBeforeUnmount(() => selected.value.forEach((item) => URL.revokeObjectURL(item.previewUrl)))

async function selectFiles(files: FileList | readonly File[]): Promise<void> {
  error.value = null
  const limits = capabilities.value
  if (limits === null || !limits.enabled) { error.value = '当前环境未启用手工检测'; return }
  const incoming = Array.from(files)
  if (selected.value.length + incoming.length > limits.maximumItemsPerBatch) {
    error.value = `每批最多选择 ${limits.maximumItemsPerBatch} 张图片`; return
  }
  for (const file of incoming) {
    if (file.size > limits.maximumObjectBytes) { error.value = `${file.name} 超过单文件大小限制`; continue }
    try {
      const prepared = await prepareImage(file)
      if (!limits.allowedMediaTypes.includes(prepared.mediaType)) throw new Error('类型不允许')
      selected.value.push({ id: crypto.randomUUID(), prepared, previewUrl: URL.createObjectURL(file),
        addKey: crypto.randomUUID(), completeKey: crypto.randomUUID(), state: 'READY' })
    } catch { error.value = `${file.name} 的实际内容不是允许的 PNG、JPG 或 JPEG 图片` }
  }
}

function drop(event: DragEvent): void {
  const files = event.dataTransfer?.files
  if (files !== undefined) void selectFiles(files)
}

function remove(id: string): void {
  const item = selected.value.find((candidate) => candidate.id === id)
  if (item !== undefined) URL.revokeObjectURL(item.previewUrl)
  selected.value = selected.value.filter((candidate) => candidate.id !== id)
}

async function submit(): Promise<void> {
  if (submitting.value || selected.value.length === 0) return
  if (stage.value === 'OTHER' && note.value.trim() === '') { error.value = '使用阶段选择“其他”时必须填写说明'; return }
  submitting.value = true; error.value = null
  try {
    if (batchId.value === null) {
      batchId.value = (await service.create(stage.value, note.value)).batch_id
    }
    await runWithConcurrency(selected.value.filter((item) => item.state !== 'UPLOADED'), 3, uploadOne)
    if (selected.value.some((item) => item.state === 'FAILED')) {
      error.value = '部分图片上传失败；其余图片已保留，可重试失败项'
      return
    }
    const batch = await service.get(batchId.value)
    await service.submit(batch.batch_id, batch.version)
    await router.push({ name: 'manual-detection-detail', params: { id: batch.batch_id } })
  } catch { error.value = '批次提交失败；服务端已保存的状态不会由页面伪造' }
  finally { submitting.value = false }
}

async function uploadOne(item: SelectedImage): Promise<void> {
  if (batchId.value === null) return
  item.state = 'UPLOADING'; item.error = undefined
  try {
    item.intent ??= await service.addItem(batchId.value, item.prepared, item.addKey)
    await service.upload(item.intent, item.prepared.file)
    item.item = await service.complete(batchId.value, item.prepared, item.intent, item.completeKey)
    item.state = 'UPLOADED'
  } catch { item.state = 'FAILED'; item.error = '上传或确认失败' }
}

async function runWithConcurrency<T>(items: readonly T[], limit: number, action: (item: T) => Promise<void>): Promise<void> {
  let index = 0
  async function worker(): Promise<void> { while (index < items.length) { const current = items[index++]; if (current !== undefined) await action(current) } }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
}
</script>

<template>
  <section class="manual-page">
    <header><p class="eyebrow">R5 · 单图片项受控直传</p><h2>手工批量检测</h2><p class="muted">选择图片后只有一次“确认上传并检测”操作。质量和检测结论均由服务端形成。</p></header>
    <p v-if="loading" role="status" class="loading-ledger">正在读取上传能力…</p>
    <p v-if="error !== null" role="alert" class="panel-error">{{ error }}</p>
    <template v-if="!loading && capabilities?.enabled">
      <div class="drop-zone" tabindex="0" @dragover.prevent @drop.prevent="drop" @keydown.enter.prevent="($refs.picker as HTMLInputElement)?.click()" @keydown.space.prevent="($refs.picker as HTMLInputElement)?.click()">
        <input ref="picker" class="visually-hidden" type="file" multiple accept=".png,.jpg,.jpeg,image/png,image/jpeg" @change="selectFiles(($event.target as HTMLInputElement).files ?? [])" />
        <strong>点击或拖拽选择图片</strong><span>PNG、JPG、JPEG · 最多 {{ capabilities.maximumItemsPerBatch }} 张</span>
        <button type="button" class="secondary-button" @click="($refs.picker as HTMLInputElement)?.click()">选择图片</button>
      </div>
      <div class="manual-form">
        <label>使用阶段<select v-model="stage"><option value="UNSPECIFIED">未指定</option><option value="NEW_BLADE">新刀片</option><option value="AFTER_ONE_WHEEL">一轮后</option><option value="AFTER_TWO_WHEELS">两轮后</option><option value="AFTER_THREE_WHEELS">三轮后</option><option value="OTHER">其他</option></select></label>
        <label v-if="stage === 'OTHER'">阶段说明<input v-model="note" maxlength="200" /></label>
      </div>
      <p role="status">已选择 {{ selected.length }} 张图片</p>
      <ul class="preview-grid" aria-label="待上传图片">
        <li v-for="item in selected" :key="item.id"><img :src="item.previewUrl" :alt="`待上传图片 ${item.prepared.file.name}`" /><strong>{{ item.prepared.file.name }}</strong><span>{{ item.state === 'UPLOADED' ? '上传 100% 并已确认' : item.state === 'UPLOADING' ? '正在上传' : item.state }}{{ item.error ? ` · ${item.error}` : '' }}</span><button type="button" :disabled="submitting || item.state === 'UPLOADED'" @click="remove(item.id)">删除</button></li>
      </ul>
      <button type="button" class="primary-button" :disabled="submitting || selected.length === 0" @click="submit">{{ submitting ? '正在上传并提交…' : selected.some((item) => item.state === 'FAILED') ? '重试失败项并检测' : '确认上传并检测' }}</button>
    </template>
  </section>
</template>

<style scoped>
.manual-page { display: grid; gap: 1rem; }
.manual-page h2 { margin: .2rem 0; }
.drop-zone { display: grid; justify-items: center; gap: .55rem; padding: 2rem; border: 2px dashed var(--line-strong); border-radius: .7rem; background: var(--panel); }
.manual-form { display: flex; flex-wrap: wrap; gap: 1rem; }
.manual-form label { display: grid; gap: .35rem; }
.manual-form select,.manual-form input { min-width: 14rem; min-height: 2.4rem; }
.preview-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(170px,1fr)); gap: .8rem; padding: 0; list-style: none; }
.preview-grid li { display: grid; gap: .4rem; padding: .7rem; border: 1px solid var(--line); border-radius: .55rem; background: var(--panel); }
.preview-grid img { width: 100%; aspect-ratio: 4/3; object-fit: cover; border-radius: .35rem; }
.preview-grid strong,.preview-grid span { overflow-wrap: anywhere; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
</style>
