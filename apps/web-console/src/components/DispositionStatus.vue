<script setup lang="ts">
import { computed } from 'vue'

import type { BusinessDisposition } from '@/api/generated'

const props = defineProps<{
  disposition: BusinessDisposition
}>()

const presentation = computed(() => {
  switch (props.disposition) {
    case 'PASS':
      return { icon: '✓', label: '通过', description: '允许进入下一生产步骤' }
    case 'FAIL':
      return { icon: '×', label: '不通过', description: '按不合格品流程处理' }
    case 'HOLD':
      return { icon: '!', label: '暂停并等待处理', description: '不得自动放行' }
  }
})
</script>

<template>
  <div
    class="disposition"
    :class="`disposition--${disposition.toLowerCase()}`"
    role="status"
  >
    <span class="disposition__icon" aria-hidden="true">{{ presentation.icon }}</span>
    <span>
      <strong>{{ presentation.label }}</strong>
      <small>{{ presentation.description }}</small>
    </span>
  </div>
</template>
