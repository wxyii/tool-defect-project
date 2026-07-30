<script setup lang="ts">
import DispositionStatus from '@/components/DispositionStatus.vue'
</script>

<template>
  <section class="workstation-grid" aria-label="工位实时状态">
    <article class="hero-card">
      <div>
        <p class="eyebrow">工位 R8-01 · 当前刀具</p>
        <h2>等待中心最终处置</h2>
        <p class="muted">采集已完成，检测结果需要人工复核。</p>
      </div>
      <DispositionStatus disposition="HOLD" />
    </article>

    <article class="metric-card">
      <span>本地待上传</span>
      <strong>0</strong>
      <small>后台采集服务独立运行</small>
    </article>
    <article class="metric-card">
      <span>最老任务年龄</span>
      <strong>0 秒</strong>
      <small>中心状态按采集标识对账</small>
    </article>
    <article class="metric-card">
      <span>磁盘使用率</span>
      <strong>42%</strong>
      <small>安全水位正常</small>
    </article>

    <article class="timeline-card">
      <h3>链路状态</h3>
      <ol>
        <li><span>✓</span>原图原子落盘</li>
        <li><span>✓</span>中心确认上传</li>
        <li><span>✓</span>算法执行完成</li>
        <li class="current"><span>!</span>等待人工复核</li>
      </ol>
    </article>
  </section>
</template>
