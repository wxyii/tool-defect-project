<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { QualityMetrics } from './service'
import { QualityService } from './service'
import { useApplicationApiClient } from '@/api/runtime'
import { ModelService } from '@/features/models/service'
import type { ModelVersionSummary } from '@/features/models/service'

const api = useApplicationApiClient()
const service = new QualityService(api)
const models = new ModelService(api)
const metrics = ref<QualityMetrics | null>(null)
const modelVersions = ref<readonly ModelVersionSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const startDate = ref('')
const endDate = ref('')
const modelVersionId = ref('')

onMounted(() => {
  void load()
  void loadModelVersions()
})

async function loadModelVersions(): Promise<void> {
  try {
    modelVersions.value = (
      await models.listModelVersions(undefined, { pageSize: 100 })
    ).items
  } catch {
    modelVersions.value = []
  }
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    metrics.value = await service.getMetrics({
      ...(startDate.value === '' ? {} : { startDate: startDate.value }),
      ...(endDate.value === '' ? {} : { endDate: endDate.value }),
      ...(modelVersionId.value.trim() === '' ? {} : { modelVersionId: modelVersionId.value.trim() }),
    })
  } catch {
    error.value = '质量指标暂时无法读取'
  } finally {
    loading.value = false
  }
}

function percent(value: number): string {
  return `${(value * 100).toFixed(2)}%`
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  if (!Number.isFinite(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <section class="records-page">
    <header class="records-heading">
      <div>
        <p class="eyebrow">离线评测 · 全量真值基线</p>
        <h2>质量分析看板</h2>
        <p class="muted">以下指标基于回归评测流程，图表标注是否基于全量人工标注真值。</p>
      </div>
    </header>

    <form class="filter-rail" aria-label="质量看板筛选" @submit.prevent="load()">
      <label>
        开始日期
        <input v-model="startDate" type="date" />
      </label>
      <label>
        结束日期
        <input v-model="endDate" type="date" />
      </label>
      <label>
        模型版本
        <select v-model="modelVersionId">
          <option value="">全部模型版本</option>
          <option v-for="item in modelVersions" :key="item.model_version_id" :value="item.model_version_id">
            {{ item.registry_name }} · {{ item.registry_version }} · {{ item.approval_state }}
          </option>
        </select>
      </label>
      <button type="submit" class="primary-button compact">刷新指标</button>
    </form>

    <p v-if="error !== null" class="panel-error" role="alert">{{ error }}</p>
    <div v-else-if="loading" class="loading-ledger" role="status">正在汇总质量指标…</div>
    <div v-else-if="metrics === null" class="loading-ledger">暂无指标数据</div>

    <template v-else>
      <div class="workstation-grid" style="margin-top: 14px">
        <div class="hero-card workstation-hero">
          <div>
            <h2>质量概要</h2>
            <p class="muted">
              时间窗口 {{ formatDate(metrics.time_window.start) }} 至
              {{ formatDate(metrics.time_window.end) }}，
              共 {{ metrics.total_sample_count }} 个样本。
            </p>
            <span
              :class="['capture-code', metrics.based_on_full_ground_truth ? '' : '']"
              :style="metrics.based_on_full_ground_truth
                ? { borderColor: 'var(--success-line)', color: 'var(--success)', background: 'var(--success-bg)' }
                : { borderColor: 'var(--warning-line)', color: 'var(--warning)', background: 'var(--warning-bg)' }"
            >
              {{ metrics.based_on_full_ground_truth ? '基于全量人工标注真值' : '基于部分抽样真值' }}
            </span>
          </div>
          <div class="metric-card">
            <span>自动通过误放率</span>
            <strong>{{ percent(metrics.auto_pass_fail_rate) }}</strong>
            <small>仅展示后端真实指标；最终门禁和处置由后端策略返回</small>
          </div>
        </div>

        <div class="metric-card">
          <span>模型推翻率</span>
          <strong>{{ percent(metrics.model_overturn_rate) }}</strong>
          <small>算法结论被人工复核推翻的比例</small>
        </div>

        <div class="metric-card">
          <span>遗漏检出数</span>
          <strong>{{ metrics.missed_detection_count }}</strong>
          <small>人工发现但算法未标记的缺陷</small>
        </div>

        <div class="metric-card">
          <span>误报数</span>
          <strong>{{ metrics.false_positive_count }}</strong>
          <small>算法标记但人工确认无缺陷</small>
        </div>

        <div class="timeline-card" v-if="metrics.mask_revision_reasons.length > 0">
          <div class="section-heading">
            <h3>标注修正原因分布</h3>
            <span>基于 {{ metrics.total_sample_count }} 个样本</span>
          </div>
          <table class="panel" style="width: 100%; box-shadow: none; border: none">
            <thead>
              <tr>
                <th>修正原因</th>
                <th>数量</th>
                <th>占比</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="reason in metrics.mask_revision_reasons" :key="reason.reason">
                <td>{{ reason.reason }}</td>
                <td style="font-family: var(--font-mono)">{{ reason.count }}</td>
                <td style="font-family: var(--font-mono)">{{ percent(reason.percentage) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-else class="detail-section" style="grid-column: 1 / -1">
          <div class="section-heading">
            <h3>标注修正原因</h3>
          </div>
          <p class="muted">当前时间窗口内无标注修正记录。</p>
        </div>
      </div>
    </template>
  </section>
</template>
