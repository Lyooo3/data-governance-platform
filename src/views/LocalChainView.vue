<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { Entity } from '../api/client'
import { local } from '../local/shared'
import { dateText } from '../stores/platform'
import DataTable from '../components/DataTable.vue'
const route = useRoute(),
  rows = ref<Entity[]>([]),
  name = ref(''),
  error = ref('')
const names = computed(() => [...new Set(rows.value.map((r) => r.name))])
const filtered = computed(() => rows.value.filter((r) => !name.value || r.name === name.value))
async function load() {
  try {
    rows.value = (await local('chain')).list
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  }
}
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>{{ route.meta.title }}</h1>
      <p>展示本地流程与检测任务各质量节点的实际检查结果，可追溯到运行明细。</p>
    </div>
    <button @click="load">刷新</button>
  </div>
  <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
  <section class="panel">
    <label class="inline-label"
      >流程或任务<select v-model="name">
        <option value="">全部记录</option>
        <option v-for="n in names" :key="n">{{ n }}</option>
      </select></label
    ><DataTable
      :rows="filtered"
      :columns="[
        { key: 'name', label: '任务' },
        { key: 'nodeName', label: '质量节点' },
        { key: 'total', label: '检查数' },
        { key: 'invalid', label: '问题数' },
        { key: 'passRate', label: '合格率%' },
        { key: 'finishedAt', label: '完成时间' },
      ]"
      ><template #finishedAt="{ row }">{{ dateText(row.finishedAt) }}</template
      ><template #actions="{ row }"
        ><RouterLink :to="'/develop/runs?run=' + row.runId">运行报告</RouterLink></template
      ></DataTable
    >
  </section>
</template>
