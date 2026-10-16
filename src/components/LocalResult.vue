<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Entity } from '../api/client'
import DataTable from './DataTable.vue'
import { metricsLabel, tableColumns, downloadJson } from '../local/shared'
const props = defineProps<{ value?: Entity }>()
const page = ref(1)
watch(
  () => props.value,
  () => (page.value = 1),
)
const rows = computed(() => props.value?.rows || [])
const displayed = computed(() => rows.value.slice((page.value - 1) * 20, page.value * 20))
</script>
<template>
  <section v-if="value" class="panel local-result">
    <div class="local-section-head">
      <h2>{{ value.name || '结果明细' }}</h2>
      <button @click="downloadJson(value, value.name || '本地结果')">下载结果JSON</button>
    </div>
    <div class="local-metrics">
      <div v-for="(number, key) in value.metrics || {}" :key="key">
        <small>{{ metricsLabel[String(key)] || key }}</small
        ><strong>{{ number }}</strong>
      </div>
    </div>
    <p v-if="value.outputDatasetId">
      <RouterLink :to="'/access/preview?dataset=' + value.outputDatasetId"
        >查看生成的数据集 →</RouterLink
      >
    </p>
    <DataTable :rows="displayed" :columns="tableColumns(rows)" empty="本次没有结果记录" />
    <div class="pagination">
      <span>共{{ rows.length }}条 · 第{{ page }}页</span
      ><button :disabled="page <= 1" @click="page--">上一页</button
      ><button :disabled="page * 20 >= rows.length" @click="page++">下一页</button>
    </div>
  </section>
</template>
