<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

import type { ImageReference } from '@/api/generated'
import { useApplicationApiClient } from '@/api/runtime'
import { ImageTicketLoader } from '@/features/detections/image-tickets'
import { DetectionService } from '@/features/detections/service'

const props = defineProps<{
  image: ImageReference
  preview?: ImageReference
}>()

const loader = new ImageTicketLoader(
  new DetectionService(useApplicationApiClient()),
)
const previewUrl = ref<string | null>(null)
const fullUrl = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

void loadPreview()

async function loadPreview(): Promise<void> {
  if (props.preview === undefined) return
  try {
    previewUrl.value = await loader.get(props.preview.image_id)
  } catch {
    error.value = '缩略图暂不可用'
  }
}

async function loadFull(forceRefresh = false): Promise<void> {
  if (loading.value) return
  loading.value = true
  error.value = null
  try {
    fullUrl.value = await loader.get(props.image.image_id, forceRefresh)
  } catch {
    error.value = '图片授权已失效，请重试'
  } finally {
    loading.value = false
  }
}

function refreshAfterImageError(): void {
  fullUrl.value = null
  void loadFull(true)
}

onBeforeUnmount(() => loader.clear())
</script>

<template>
  <article class="evidence-image">
    <div class="evidence-image__stage">
      <img
        v-if="fullUrl !== null"
        :src="fullUrl"
        :alt="`${image.kind} 检测证据`"
        loading="lazy"
        decoding="async"
        @error="refreshAfterImageError"
      />
      <img
        v-else-if="previewUrl !== null"
        :src="previewUrl"
        :alt="`${image.kind} 缩略预览`"
        loading="lazy"
        decoding="async"
      />
      <div v-else class="evidence-image__placeholder" aria-hidden="true">
        {{ image.kind }}
      </div>
    </div>
    <div class="evidence-image__caption">
      <div>
        <strong>{{ image.kind }}</strong>
        <small>{{ image.width }} × {{ image.height }} · {{ image.image_role ?? '派生证据' }}</small>
      </div>
      <button
        type="button"
        class="secondary-button"
        :disabled="loading"
        @click="loadFull(false)"
      >
        {{ loading ? '申请中…' : fullUrl === null ? '查看全分辨率' : '重新授权' }}
      </button>
    </div>
    <p v-if="error !== null" class="inline-error" role="alert">{{ error }}</p>
  </article>
</template>
