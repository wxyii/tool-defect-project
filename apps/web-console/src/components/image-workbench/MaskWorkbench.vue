<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { binaryMaskPng } from './binary-png'
import {
  MaskDraftStore,
  MaskHistory,
  type MaskPoint,
  type MaskTool,
} from './mask-history'

const props = defineProps<{
  readonly reviewTaskId: string
  readonly sourceUrl: string
  readonly overlayUrl?: string | null
  readonly width: number
  readonly height: number
}>()
const emit = defineEmits<{
  'mask-ready': [blob: Blob]
  'source-error': []
  'source-ready': []
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
const history = new MaskHistory()
const draftStore = new MaskDraftStore(window.localStorage)
const revision = ref(0)
const tool = ref<MaskTool>('brush')
const radius = ref(0.012)
const overlayVisible = ref(false)
const drawing = ref(false)
const currentPoints = ref<MaskPoint[]>([])
const exporting = ref(false)
const restored = ref(false)
const canUndo = computed(() => (revision.value >= 0 ? history.canUndo : false))
const canRedo = computed(() => (revision.value >= 0 ? history.canRedo : false))
const hasMarks = computed(
  () => (revision.value >= 0 ? history.strokes.length > 0 : false),
)

onMounted(() => {
  setCanvasDimensions()
  restored.value = draftStore.load(props.reviewTaskId, history)
  revision.value += 1
  render()
})

watch(
  () => [props.width, props.height],
  () => {
    setCanvasDimensions()
    render()
  },
)
watch([revision, radius, tool], render)

function setCanvasDimensions(): void {
  if (canvas.value === null) return
  const scale = Math.min(900 / props.width, 640 / props.height, 1)
  canvas.value.width = Math.max(1, Math.round(props.width * scale))
  canvas.value.height = Math.max(1, Math.round(props.height * scale))
}

function begin(event: PointerEvent): void {
  if (canvas.value === null) return
  canvas.value.setPointerCapture(event.pointerId)
  drawing.value = true
  currentPoints.value = [point(event)]
  render()
}

function move(event: PointerEvent): void {
  if (!drawing.value) return
  currentPoints.value.push(point(event))
  render()
}

function finish(event: PointerEvent): void {
  if (!drawing.value || canvas.value === null) return
  drawing.value = false
  currentPoints.value.push(point(event))
  history.add({
    tool: tool.value,
    radius: radius.value,
    points: currentPoints.value,
  })
  currentPoints.value = []
  persist()
}

function point(event: PointerEvent): MaskPoint {
  const bounds = canvas.value?.getBoundingClientRect()
  if (bounds === undefined) return { x: 0, y: 0 }
  return {
    x: clamp((event.clientX - bounds.left) / bounds.width),
    y: clamp((event.clientY - bounds.top) / bounds.height),
  }
}

function render(): void {
  const target = canvas.value
  if (target === null) return
  const context = target.getContext('2d')
  if (context === null) return
  context.clearRect(0, 0, target.width, target.height)
  for (const stroke of [
    ...history.strokes,
    ...(currentPoints.value.length === 0
      ? []
      : [{ tool: tool.value, radius: radius.value, points: currentPoints.value }]),
  ]) {
    const first = stroke.points[0]
    if (first === undefined) continue
    context.beginPath()
    context.moveTo(first.x * target.width, first.y * target.height)
    for (const item of stroke.points.slice(1)) {
      context.lineTo(item.x * target.width, item.y * target.height)
    }
    context.strokeStyle = stroke.tool === 'brush'
      ? 'rgba(231, 64, 46, 0.84)'
      : 'rgba(255, 255, 255, 0.95)'
    context.globalCompositeOperation =
      stroke.tool === 'brush' ? 'source-over' : 'destination-out'
    context.lineCap = 'round'
    context.lineJoin = 'round'
    context.lineWidth = Math.max(
      2,
      stroke.radius * Math.min(target.width, target.height) * 2,
    )
    context.stroke()
  }
  context.globalCompositeOperation = 'source-over'
}

function undo(): void {
  history.undo()
  persist()
}

function redo(): void {
  history.redo()
  persist()
}

function clear(): void {
  history.clear()
  persist()
}

function persist(): void {
  draftStore.save(props.reviewTaskId, history)
  revision.value += 1
}

async function exportMask(): Promise<void> {
  exporting.value = true
  try {
    emit(
      'mask-ready',
      await binaryMaskPng(props.width, props.height, history.strokes),
    )
  } finally {
    exporting.value = false
  }
}

function clamp(value: number): number {
  return Math.max(0, Math.min(1, value))
}
</script>

<template>
  <section class="mask-workbench" aria-label="人工掩膜标注工作台">
    <header class="mask-toolbar">
      <div class="tool-group" role="group" aria-label="标注工具">
        <button
          type="button"
          :aria-pressed="tool === 'brush'"
          @click="tool = 'brush'"
        >
          ● 画笔
        </button>
        <button
          type="button"
          :aria-pressed="tool === 'eraser'"
          @click="tool = 'eraser'"
        >
          ○ 橡皮
        </button>
      </div>
      <label class="radius-control">
        笔刷
        <input
          v-model.number="radius"
          type="range"
          min="0.002"
          max="0.05"
          step="0.002"
        />
      </label>
      <label class="overlay-control">
        <input
          v-model="overlayVisible"
          type="checkbox"
          :disabled="!overlayUrl"
        />
        显示模型叠加
      </label>
      <div class="history-controls">
        <button type="button" :disabled="!canUndo" @click="undo">撤销</button>
        <button type="button" :disabled="!canRedo" @click="redo">重做</button>
        <button type="button" :disabled="!hasMarks" @click="clear">清空</button>
      </div>
    </header>

    <div
      class="mask-stage"
      :style="{ aspectRatio: `${width} / ${height}` }"
    >
      <img
        :src="sourceUrl"
        alt="受控原始检测图像"
        @error="emit('source-error')"
        @load="emit('source-ready')"
      />
      <img
        v-if="overlayUrl && overlayVisible"
        :src="overlayUrl"
        class="model-overlay"
        alt="模型证据叠加层"
      />
      <canvas
        ref="canvas"
        aria-label="人工掩膜绘制区域"
        tabindex="0"
        @pointerdown="begin"
        @pointermove="move"
        @pointerup="finish"
        @pointercancel="finish"
      />
    </div>

    <footer class="mask-footer">
      <p>
        <span v-if="restored">已恢复本机稀疏笔迹草稿；草稿不是业务事实。</span>
        <span v-else>仅保存稀疏笔迹，不保存原图或临时地址。</span>
      </p>
      <button
        type="button"
        class="secondary-button"
        :disabled="!hasMarks || exporting"
        @click="exportMask"
      >
        {{ exporting ? '正在生成单通道 PNG…' : '生成并使用人工掩膜' }}
      </button>
    </footer>
  </section>
</template>
