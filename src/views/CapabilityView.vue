<script setup lang="ts">
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
const route = useRoute()
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>{{ route.meta.title }}</h1>
      <p>原平台对应入口已迁移到可维护的Vue 3页面。</p>
    </div>
  </div>
  <section class="panel capability-panel">
    <span class="capability-icon"><Icon name="settings" :size="36" /></span
    ><span class="badge draft">业务能力尚未启用</span>
    <h2>{{ route.meta.title }}</h2>
    <p>{{ (route.meta.page as { description: string }).description }}</p>
    <div class="capability-links">
      <RouterLink class="primary button" to="/develop/flows">治理流程</RouterLink
      ><RouterLink class="button" to="/quality/rules">质量规则</RouterLink
      ><a class="button" href="/docs" target="_blank" rel="noopener">查看后端接口</a>
    </div>
  </section>
</template>
