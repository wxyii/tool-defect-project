<script setup lang="ts">
import { ref } from 'vue'
import { useApplicationApiClient } from '@/api/runtime'
import { TrainingService } from './service'
import type { TrainingRunView } from './service'
import type { Uuid } from '@/api/generated'

const service = new TrainingService(useApplicationApiClient())
const datasetVersionId = ref('')
const initialModelVersionId = ref('')
const trainingConfigVersion = ref('')
const lookupRunId = ref('')
const run = ref<TrainingRunView | null>(null)
const jobId = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

async function createRun(): Promise<void> {
  error.value = null
  jobId.value = null
  if (!isUuid(datasetVersionId.value) || trainingConfigVersion.value.trim() === '') {
    error.value = '数据集版本必须是 UUID，训练配置版本不能为空'
    return
  }
  loading.value = true
  try {
    const accepted = await service.create({
      dataset_version_id: datasetVersionId.value.trim() as Uuid,
      initial_model_version_id: initialModelVersionId.value.trim() === ''
        ? null
        : initialModelVersionId.value.trim() as Uuid,
      training_config_version: trainingConfigVersion.value.trim(),
    })
    jobId.value = accepted.job_id
  } catch {
    error.value = '训练任务创建失败；请先确认数据集已冻结且配置已登记'
  } finally {
    loading.value = false
  }
}

async function lookup(): Promise<void> {
  error.value = null
  run.value = null
  if (!isUuid(lookupRunId.value)) {
    error.value = '训练运行 ID 必须是 UUID'
    return
  }
  loading.value = true
  try {
    run.value = await service.get(lookupRunId.value.trim())
  } catch {
    error.value = '训练运行暂时无法读取'
  } finally {
    loading.value = false
  }
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.trim())
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN') : iso
}
</script>

<template>
  <section class="records-page">
    <header class="records-heading">
      <div>
        <p class="eyebrow">可复现训练 · 版本锁定</p>
        <h2>训练运行</h2>
        <p class="muted">训练请求只引用已冻结数据集和版本化配置；页面不会伪造运行完成或模型权重。</p>
      </div>
      <span class="records-count">{{ jobId === null ? '等待提交' : '任务已排队' }}</span>
    </header>

    <div class="page-stack">
      <form class="panel" aria-label="创建训练运行" @submit.prevent="createRun">
        <div class="section-heading"><h3>创建离线训练任务</h3><span class="muted">异步执行</span></div>
        <div class="filter-rail">
          <label>数据集版本 UUID<input v-model="datasetVersionId" required placeholder="dataset-version-uuid" /></label>
          <label>初始化模型 UUID（可选）<input v-model="initialModelVersionId" placeholder="model-version-uuid" /></label>
          <label>训练配置版本<input v-model="trainingConfigVersion" required placeholder="2026.07.31" /></label>
          <button class="primary-button compact" type="submit" :disabled="loading">{{ loading ? '提交中…' : '创建训练任务' }}</button>
        </div>
        <p v-if="jobId !== null" class="decision-caveat">已排队任务 ID：<span class="hash-text">{{ jobId }}</span>。后端完成后再用运行 ID读取证据。</p>
      </form>

      <form class="panel" aria-label="读取训练运行" @submit.prevent="lookup">
        <div class="section-heading"><h3>读取运行证据</h3><span class="muted">只读</span></div>
        <div class="filter-rail">
          <label>训练运行 UUID<input v-model="lookupRunId" required placeholder="training-run-uuid" /></label>
          <button class="secondary-button compact" type="submit" :disabled="loading">查询运行</button>
        </div>
        <dl v-if="run !== null" class="version-grid">
          <dt>运行 ID</dt><dd class="hash-text">{{ run.id }}</dd>
          <dt>版本</dt><dd>{{ run.version }}</dd>
          <dt>状态</dt><dd><span class="state-stamp">{{ run.status }}</span></dd>
          <dt>创建时间</dt><dd>{{ formatDate(run.created_at) }}</dd>
        </dl>
      </form>
    </div>
    <p v-if="error !== null" class="panel-error" role="alert">{{ error }}</p>
  </section>
</template>
