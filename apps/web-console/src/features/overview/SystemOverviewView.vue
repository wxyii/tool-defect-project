<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { useApplicationApiClient } from '@/api/runtime'

import { OverviewService } from './service'
import type { SystemOverview } from './service'

interface ComparisonRow {
  readonly label: string
  readonly current: number
  readonly previous: number
  readonly tone: 'good' | 'warn' | 'bad'
}

interface ComparisonPanel {
  readonly title: string
  readonly note: string
  readonly currentTotal: number
  readonly previousTotal: number
  readonly rows: readonly ComparisonRow[]
}

const service = new OverviewService(useApplicationApiClient())
const snapshot = ref<SystemOverview | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
let timer: ReturnType<typeof setInterval> | undefined

const stationRatio = computed(() => {
  if (snapshot.value === null || snapshot.value.fleet.stations_total === 0) return 0
  return snapshot.value.fleet.stations_online / snapshot.value.fleet.stations_total
})

const deviceHealthyRatio = computed(() => {
  if (snapshot.value === null || snapshot.value.fleet.devices_total === 0) return 0
  const healthy = snapshot.value.fleet.devices_online
    + snapshot.value.fleet.devices_degraded
  return healthy / snapshot.value.fleet.devices_total
})

const comparisonPanels = computed<readonly ComparisonPanel[]>(() => {
  const value = snapshot.value
  if (value === null) return []
  const outcomeCurrent = total([
    value.outcome_comparison.current.qualified,
    value.outcome_comparison.current.unqualified,
    value.outcome_comparison.current.inconclusive,
  ])
  const outcomePrevious = total([
    value.outcome_comparison.previous.qualified,
    value.outcome_comparison.previous.unqualified,
    value.outcome_comparison.previous.inconclusive,
  ])
  const qualityCurrent = total([
    value.quality_comparison.current.ok,
    value.quality_comparison.current.warning,
    value.quality_comparison.current.rejected,
  ])
  const qualityPrevious = total([
    value.quality_comparison.previous.ok,
    value.quality_comparison.previous.warning,
    value.quality_comparison.previous.rejected,
  ])
  return [
    {
      title: '模型结论分布',
      note: '按授权范围内已完成的检测结果计数',
      currentTotal: outcomeCurrent,
      previousTotal: outcomePrevious,
      rows: [
        {
          label: '合格',
          current: value.outcome_comparison.current.qualified,
          previous: value.outcome_comparison.previous.qualified,
          tone: 'good',
        },
        {
          label: '不合格',
          current: value.outcome_comparison.current.unqualified,
          previous: value.outcome_comparison.previous.unqualified,
          tone: 'bad',
        },
        {
          label: '不确定',
          current: value.outcome_comparison.current.inconclusive,
          previous: value.outcome_comparison.previous.inconclusive,
          tone: 'warn',
        },
      ],
    },
    {
      title: '采集质量分布',
      note: '按采集事件质量状态计数，不替代最终处置',
      currentTotal: qualityCurrent,
      previousTotal: qualityPrevious,
      rows: [
        {
          label: '正常',
          current: value.quality_comparison.current.ok,
          previous: value.quality_comparison.previous.ok,
          tone: 'good',
        },
        {
          label: '警告',
          current: value.quality_comparison.current.warning,
          previous: value.quality_comparison.previous.warning,
          tone: 'warn',
        },
        {
          label: '拒绝',
          current: value.quality_comparison.current.rejected,
          previous: value.quality_comparison.previous.rejected,
          tone: 'bad',
        },
      ],
    },
  ]
})

onMounted(() => {
  void load()
  timer = setInterval(() => void load(true), 15_000)
})

onUnmounted(() => {
  if (timer !== undefined) clearInterval(timer)
})

async function load(silent = false): Promise<void> {
  if (loading.value) return
  loading.value = true
  if (!silent) error.value = null
  try {
    snapshot.value = await service.get()
    error.value = null
  } catch {
    error.value = snapshot.value === null
      ? '系统态势暂时无法读取，请确认业务服务和数据库连接状态。'
      : '自动刷新失败，当前保留上一次可信快照。'
  } finally {
    loading.value = false
  }
}

function total(values: readonly number[]): number {
  return values.reduce((sum, value) => sum + value, 0)
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

function barWidth(value: number, denominator: number): string {
  if (denominator <= 0) return '0%'
  return `${Math.min(100, Math.max(0, value / denominator * 100))}%`
}

function number(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function timestamp(value: string | null): string {
  if (value === null) return '尚未生效'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function duration(seconds: number): string {
  if (seconds < 60) return `${seconds} 秒`
  if (seconds < 3_600) return `${Math.floor(seconds / 60)} 分钟`
  const hours = Math.floor(seconds / 3_600)
  const minutes = Math.floor(seconds % 3_600 / 60)
  return `${hours} 小时 ${minutes} 分钟`
}

function latency(value: number | null): string {
  if (value === null) return '暂无样本'
  if (value < 1_000) return `${value.toFixed(0)} 毫秒`
  return `${(value / 1_000).toFixed(2)} 秒`
}

function shortId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-6)}`
}
</script>

<template>
  <section class="overview-page">
    <header class="overview-masthead">
      <div>
        <p class="eyebrow">运行态势台 · 每 15 秒更新</p>
        <h2>系统总览</h2>
        <p v-if="snapshot !== null" class="overview-window">
          当前统计窗：{{ timestamp(snapshot.window.current_start) }} 至
          {{ timestamp(snapshot.window.current_end) }} · {{ snapshot.window.timezone }}
        </p>
        <p v-else class="overview-window">聚合当前账号获授权的数据范围</p>
      </div>
      <div class="overview-refresh">
        <span class="live-indicator">
          <i aria-hidden="true"></i>
          {{ error === null ? '态势链路正常' : '快照保留中' }}
        </span>
        <span v-if="snapshot !== null" class="generated-time">
          生成于 {{ timestamp(snapshot.generated_at) }}
        </span>
        <button
          type="button"
          class="secondary-button"
          :disabled="loading"
          @click="load()"
        >
          {{ loading ? '正在刷新' : '立即刷新' }}
        </button>
      </div>
    </header>

    <p v-if="error !== null" class="overview-alert" role="alert">{{ error }}</p>
    <div v-if="loading && snapshot === null" class="overview-loading" role="status">
      <span></span><span></span><span></span>
      正在建立运行态势快照…
    </div>

    <template v-if="snapshot !== null">
      <section class="disposition-board" aria-labelledby="capture-heading">
        <div class="board-title">
          <div>
            <span>今日采集</span>
            <strong id="capture-heading">{{ number(snapshot.captures.total) }}</strong>
          </div>
          <small>
            分母为当前统计窗内 {{ number(snapshot.captures.total) }} 次采集
          </small>
        </div>
        <div class="disposition-cell disposition-cell--pass">
          <span class="disposition-mark">✓</span>
          <div><small>通过</small><strong>{{ number(snapshot.captures.pass) }}</strong></div>
          <em>{{ percent(snapshot.captures.total === 0 ? 0 : snapshot.captures.pass / snapshot.captures.total) }}</em>
        </div>
        <div class="disposition-cell disposition-cell--fail">
          <span class="disposition-mark">×</span>
          <div><small>不通过</small><strong>{{ number(snapshot.captures.fail) }}</strong></div>
          <em>{{ percent(snapshot.captures.total === 0 ? 0 : snapshot.captures.fail / snapshot.captures.total) }}</em>
        </div>
        <div class="disposition-cell disposition-cell--hold">
          <span class="disposition-mark">!</span>
          <div><small>暂停处理</small><strong>{{ number(snapshot.captures.hold) }}</strong></div>
          <em>{{ percent(snapshot.captures.total === 0 ? 0 : snapshot.captures.hold / snapshot.captures.total) }}</em>
        </div>
        <div class="disposition-cell disposition-cell--pending">
          <span class="disposition-mark">○</span>
          <div><small>尚未处置</small><strong>{{ number(snapshot.captures.unresolved) }}</strong></div>
          <em>{{ percent(snapshot.captures.total === 0 ? 0 : snapshot.captures.unresolved / snapshot.captures.total) }}</em>
        </div>
      </section>

      <div class="operations-grid">
        <section class="ops-panel review-panel">
          <div class="panel-kicker"><span>01</span>人工复核积压</div>
          <div class="panel-headline">
            <strong>{{ number(snapshot.reviews.total) }}</strong>
            <span>个活跃任务</span>
          </div>
          <dl class="compact-metrics">
            <div><dt>待领取</dt><dd>{{ number(snapshot.reviews.pending) }}</dd></div>
            <div><dt>处理中</dt><dd>{{ number(snapshot.reviews.claimed) }}</dd></div>
            <div><dt>等待二审</dt><dd>{{ number(snapshot.reviews.second_review_pending) }}</dd></div>
            <div><dt>已升级</dt><dd class="danger-ink">{{ number(snapshot.reviews.escalated) }}</dd></div>
          </dl>
          <div class="age-ruler">
            <span>最久等待</span>
            <strong>{{ duration(snapshot.reviews.oldest_age_seconds) }}</strong>
          </div>
        </section>

        <section class="ops-panel fleet-panel">
          <div class="panel-kicker"><span>02</span>工位与设备</div>
          <div class="ratio-row">
            <div>
              <strong>{{ snapshot.fleet.stations_online }}/{{ snapshot.fleet.stations_total }}</strong>
              <span>工位在线</span>
            </div>
            <em>{{ percent(stationRatio) }}</em>
          </div>
          <div class="health-track" role="img" :aria-label="`工位在线率 ${percent(stationRatio)}`">
            <i :style="{ width: percent(stationRatio) }"></i>
          </div>
          <dl class="fleet-states">
            <div class="online"><dt>设备在线</dt><dd>{{ snapshot.fleet.devices_online }}</dd></div>
            <div class="degraded"><dt>设备降级</dt><dd>{{ snapshot.fleet.devices_degraded }}</dd></div>
            <div class="offline"><dt>设备离线</dt><dd>{{ snapshot.fleet.devices_offline }}</dd></div>
          </dl>
          <p class="panel-footnote">
            {{ snapshot.fleet.devices_total }} 台设备 · 健康或降级占
            {{ percent(deviceHealthyRatio) }} · 心跳阈值
            {{ snapshot.fleet.heartbeat_freshness_seconds }} 秒
          </p>
        </section>

        <section class="ops-panel inference-panel">
          <div class="panel-kicker"><span>03</span>推理执行面</div>
          <div class="queue-strip">
            <div><small>排队</small><strong>{{ snapshot.inference.queued }}</strong></div>
            <div><small>运行</small><strong>{{ snapshot.inference.running }}</strong></div>
            <div><small>等待重试</small><strong>{{ snapshot.inference.retry_wait }}</strong></div>
            <div class="dead"><small>终止</small><strong>{{ snapshot.inference.dead }}</strong></div>
          </div>
          <div class="latency-readout">
            <span>当前窗完成 {{ number(snapshot.inference.completed_in_window) }} 次</span>
            <strong>第 95 百分位 {{ latency(snapshot.inference.p95_duration_ms) }}</strong>
          </div>
          <p class="panel-footnote">
            最近 24 小时终止 {{ number(snapshot.inference.failures_24h) }} 次；技术失败不会计为通过。
          </p>
        </section>

        <section class="ops-panel model-panel">
          <div class="panel-kicker"><span>04</span>生产模型</div>
          <template v-if="snapshot.model_runtime.production !== null">
            <div class="model-plate">
              <span>当前生产</span>
              <strong>
                {{ snapshot.model_runtime.production.registry_name ?? '未登记仓库名' }}
              </strong>
              <code>
                {{ snapshot.model_runtime.production.registry_version ?? shortId(snapshot.model_runtime.production.model_version_id) }}
              </code>
            </div>
            <div class="model-meta">
              <span>流量 {{ percent(snapshot.model_runtime.production.traffic_ratio) }}</span>
              <span>生效 {{ timestamp(snapshot.model_runtime.production.effective_at) }}</span>
            </div>
          </template>
          <div v-else class="model-empty">
            <strong>未发现活跃生产部署</strong>
            <span>系统不会把未知模型状态显示为正常。</span>
          </div>
          <div class="runtime-badges">
            <span>影子 {{ snapshot.model_runtime.active_shadow_deployments }}</span>
            <span>金丝雀 {{ snapshot.model_runtime.active_canary_deployments }}</span>
            <span>金丝雀流量 {{ percent(snapshot.model_runtime.canary_traffic_ratio) }}</span>
          </div>
        </section>
      </div>

      <div class="comparison-grid">
        <section v-for="panel in comparisonPanels" :key="panel.title" class="comparison-panel">
          <header>
            <div><h3>{{ panel.title }}</h3><p>{{ panel.note }}</p></div>
            <div class="period-key"><span>本窗</span><span>前窗</span></div>
          </header>
          <div v-for="row in panel.rows" :key="row.label" class="comparison-row">
            <strong>{{ row.label }}</strong>
            <div class="paired-bars">
              <div>
                <i :class="`tone-${row.tone}`" :style="{ width: barWidth(row.current, panel.currentTotal) }"></i>
              </div>
              <div>
                <i :class="`tone-${row.tone}`" :style="{ width: barWidth(row.previous, panel.previousTotal) }"></i>
              </div>
            </div>
            <code>{{ row.current }} / {{ row.previous }}</code>
          </div>
          <footer>
            本窗分母 {{ number(panel.currentTotal) }} · 前窗分母 {{ number(panel.previousTotal) }}
          </footer>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.overview-page {
  display: grid;
  gap: 14px;
  max-width: 1500px;
  margin: 0 auto;
}

.overview-masthead {
  position: relative;
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  min-height: 112px;
  padding: 22px 24px 20px 28px;
  overflow: hidden;
  border: 1px solid #cfe0ee;
  border-left: 5px solid var(--accent-deep);
  border-radius: 4px;
  background:
    linear-gradient(90deg, rgb(255 255 255 / 97%), rgb(247 252 255 / 94%)),
    repeating-linear-gradient(90deg, transparent 0 39px, #dcecf7 40px);
  box-shadow: var(--shadow-card);
}

.overview-masthead::after {
  position: absolute;
  top: 0;
  right: 0;
  width: 170px;
  height: 4px;
  background: linear-gradient(90deg, transparent, var(--cyan));
  content: "";
}

.overview-masthead h2 {
  margin: 5px 0 4px;
  font-size: clamp(24px, 2.2vw, 32px);
  letter-spacing: 0.02em;
}

.overview-window {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.overview-refresh {
  display: grid;
  grid-template-columns: auto auto;
  gap: 6px 14px;
  align-items: center;
  justify-items: end;
}

.overview-refresh button {
  grid-row: 1 / 3;
  grid-column: 2;
}

.live-indicator {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--success);
  font-size: 12px;
  font-weight: 700;
}

.live-indicator i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentcolor;
  box-shadow: 0 0 0 4px rgb(31 163 114 / 12%);
}

.generated-time {
  color: var(--faint);
  font-family: var(--font-mono);
  font-size: 10.5px;
}

.overview-alert,
.overview-loading {
  margin: 0;
  padding: 12px 16px;
  border: 1px solid var(--warning-line);
  border-radius: 4px;
  color: #8b5b0c;
  background: var(--warning-bg);
}

.overview-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 160px;
  justify-content: center;
  border-color: var(--line-strong);
  color: var(--muted);
  background: var(--panel);
}

.overview-loading span {
  width: 7px;
  height: 24px;
  background: var(--accent);
  animation: overview-pulse 900ms ease-in-out infinite alternate;
}

.overview-loading span:nth-child(2) { animation-delay: 150ms; }
.overview-loading span:nth-child(3) { animation-delay: 300ms; }

@keyframes overview-pulse {
  to { height: 8px; opacity: 0.35; }
}

.disposition-board {
  display: grid;
  grid-template-columns: minmax(220px, 1.3fr) repeat(4, minmax(145px, 1fr));
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel);
  box-shadow: var(--shadow-card);
}

.board-title,
.disposition-cell {
  min-height: 118px;
  padding: 18px 20px;
}

.board-title {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  color: #fff;
  background: #123e61;
}

.board-title div { display: flex; align-items: baseline; gap: 14px; }
.board-title span { font-size: 12px; letter-spacing: 0.12em; }
.board-title strong { font-family: var(--font-mono); font-size: 38px; }
.board-title small { color: #bed6e8; line-height: 1.5; }

.disposition-cell {
  position: relative;
  display: grid;
  grid-template-columns: 34px 1fr auto;
  gap: 10px;
  align-items: center;
  border-left: 1px solid var(--line);
}

.disposition-cell::after {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 3px;
  background: currentcolor;
  content: "";
}

.disposition-cell--pass { color: var(--success); }
.disposition-cell--fail { color: var(--danger); }
.disposition-cell--hold { color: var(--warning); }
.disposition-cell--pending { color: var(--faint); }

.disposition-mark {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid currentcolor;
  border-radius: 50%;
  font-family: var(--font-mono);
  font-size: 18px;
}

.disposition-cell div { display: grid; gap: 3px; }
.disposition-cell small { color: var(--muted); }
.disposition-cell strong { color: var(--ink); font-family: var(--font-mono); font-size: 27px; }
.disposition-cell em { font-family: var(--font-mono); font-size: 11px; font-style: normal; }

.operations-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.ops-panel,
.comparison-panel {
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel);
  box-shadow: var(--shadow-card);
}

.panel-kicker {
  display: flex;
  gap: 9px;
  align-items: center;
  margin-bottom: 18px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
}

.panel-kicker span {
  color: var(--accent-deep);
  font-family: var(--font-mono);
}

.panel-headline { display: flex; align-items: baseline; gap: 9px; margin-bottom: 17px; }
.panel-headline strong { font-family: var(--font-mono); font-size: 35px; }
.panel-headline span { color: var(--muted); }

.compact-metrics {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1px;
  margin: 0;
  background: var(--line);
}

.compact-metrics div,
.fleet-states div {
  padding: 9px 10px;
  background: #f8fafc;
}

.compact-metrics dt,
.fleet-states dt { color: var(--muted); font-size: 10.5px; }
.compact-metrics dd,
.fleet-states dd { margin: 4px 0 0; font-family: var(--font-mono); font-size: 17px; font-weight: 700; }
.danger-ink { color: var(--danger); }

.age-ruler {
  display: flex;
  justify-content: space-between;
  margin-top: 13px;
  padding-top: 11px;
  border-top: 1px dashed var(--line-strong);
  color: var(--muted);
  font-size: 11px;
}

.age-ruler strong { color: var(--warning); }

.ratio-row { display: flex; align-items: end; justify-content: space-between; }
.ratio-row div { display: grid; gap: 2px; }
.ratio-row strong { font-family: var(--font-mono); font-size: 27px; }
.ratio-row span { color: var(--muted); font-size: 11px; }
.ratio-row em { color: var(--success); font-family: var(--font-mono); font-style: normal; }

.health-track {
  height: 7px;
  margin: 13px 0 16px;
  overflow: hidden;
  border-radius: 9px;
  background: #e9eef3;
}

.health-track i { display: block; height: 100%; background: var(--success); }

.fleet-states {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  margin: 0;
  background: var(--line);
}

.fleet-states .online dd { color: var(--success); }
.fleet-states .degraded dd { color: var(--warning); }
.fleet-states .offline dd { color: var(--danger); }

.queue-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border: 1px solid var(--line);
}

.queue-strip div { display: grid; gap: 5px; padding: 11px 8px; border-right: 1px solid var(--line); text-align: center; }
.queue-strip div:last-child { border-right: 0; }
.queue-strip small { color: var(--muted); font-size: 9.5px; }
.queue-strip strong { font-family: var(--font-mono); font-size: 18px; }
.queue-strip .dead strong { color: var(--danger); }

.latency-readout { display: grid; gap: 5px; margin-top: 18px; }
.latency-readout span { color: var(--muted); font-size: 11px; }
.latency-readout strong { color: var(--accent-ink); font-size: 14px; }
.panel-footnote { margin: 16px 0 0; color: var(--faint); font-size: 10.5px; line-height: 1.55; }

.model-plate {
  display: grid;
  gap: 6px;
  padding: 14px;
  border-left: 3px solid var(--cyan);
  background: #eff8fb;
}

.model-plate span { color: var(--muted); font-size: 10px; letter-spacing: 0.1em; }
.model-plate strong { overflow-wrap: anywhere; font-size: 14px; }
.model-plate code { color: var(--accent-ink); font-family: var(--font-mono); }
.model-meta { display: flex; justify-content: space-between; margin: 10px 0 15px; color: var(--muted); font-size: 10.5px; }
.model-empty { display: grid; gap: 7px; min-height: 91px; padding: 14px; border: 1px dashed var(--warning-line); background: var(--warning-bg); }
.model-empty span { color: var(--muted); font-size: 11px; }
.runtime-badges { display: flex; flex-wrap: wrap; gap: 6px; }
.runtime-badges span { padding: 5px 8px; border: 1px solid #c9dfea; color: #27607c; background: #f3f9fc; font-size: 10px; }

.comparison-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.comparison-panel header { display: flex; align-items: start; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.comparison-panel h3 { margin: 0; font-size: 14px; }
.comparison-panel header p { margin: 5px 0 0; color: var(--muted); font-size: 10.5px; }
.period-key { display: flex; gap: 13px; color: var(--faint); font-size: 10px; white-space: nowrap; }
.period-key span::before { display: inline-block; width: 12px; height: 3px; margin-right: 5px; background: var(--accent); content: ""; vertical-align: middle; }
.period-key span:last-child::before { background: #b8c5d0; }

.comparison-row {
  display: grid;
  grid-template-columns: 64px 1fr 92px;
  gap: 12px;
  align-items: center;
  margin: 10px 0;
}

.comparison-row > strong { font-size: 11px; }
.comparison-row > code { color: var(--muted); font-family: var(--font-mono); font-size: 10px; text-align: right; }
.paired-bars { display: grid; gap: 4px; }
.paired-bars div { height: 7px; overflow: hidden; background: #edf1f5; }
.paired-bars i { display: block; height: 100%; min-width: 0; }
.paired-bars div:last-child i { opacity: 0.45; }
.tone-good { background: var(--success); }
.tone-warn { background: var(--warning); }
.tone-bad { background: var(--danger); }
.comparison-panel footer { margin-top: 13px; padding-top: 10px; border-top: 1px dashed var(--line); color: var(--faint); font-size: 10px; text-align: right; }

@media (width <= 1180px) {
  .disposition-board { grid-template-columns: repeat(4, 1fr); }
  .board-title { grid-column: 1 / -1; min-height: 90px; }
  .operations-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (width <= 760px) {
  .overview-masthead { align-items: start; flex-direction: column; }
  .overview-refresh { width: 100%; justify-items: start; }
  .overview-refresh button { justify-self: end; }
  .disposition-board { grid-template-columns: repeat(2, 1fr); }
  .disposition-cell { border-bottom: 1px solid var(--line); }
  .operations-grid,
  .comparison-grid { grid-template-columns: 1fr; }
}

@media (width <= 480px) {
  .disposition-board { grid-template-columns: 1fr; }
  .comparison-row { grid-template-columns: 58px 1fr; }
  .comparison-row > code { grid-column: 2; text-align: left; }
}
</style>
