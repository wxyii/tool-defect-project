<script setup lang="ts">
defineProps<{ title: string }>()
</script>

<template>
  <section class="empty-state">
    <p class="eyebrow">基础壳已就绪</p>
    <h2>{{ title }}</h2>
    <p>此入口已接入统一路由、权限和请求基础，业务页面在后续阶段建设。</p>
  </section>
</template>
