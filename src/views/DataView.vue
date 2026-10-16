<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { request } from '../api/client'
import type { Entity, Page } from '../api/client'
import { act, platform, refresh } from '../stores/platform'
import DataTable from '../components/DataTable.vue'
import Icon from '../components/Icon.vue'
const route = useRoute(),
  selected = ref(String(route.query.dataset || '')),
  rows = ref<Entity[]>([]),
  total = ref(0),
  page = ref(1),
  busy = ref(false)
const columns = computed(() => Object.keys(rows.value[0] || {}).map((key) => ({ key, label: key })))
async function load() {
  if (!selected.value) return
  busy.value = true
  await act(async () => {
    const result = await request<Page>(
      'datasets/' + selected.value + '/rows?pageNum=' + page.value + '&pageSize=20',
    )
    rows.value = result.list
    total.value = result.total
  })
  busy.value = false
}
onMounted(() =>
  act(async () => {
    await refresh()
    selected.value ||= platform.datasets[0]?.id || ''
    await load()
  }),
)
function changePage(delta: number) {
  page.value += delta
  act(load)
}
function changeDataset() {
  page.value = 1
  act(load)
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>数据预览</h1>
      <p>探索样例和导入数据，查看字段结构及分页记录。</p>
    </div>
    <RouterLink to="/access/datasets" class="button"><Icon name="plus" />管理数据集</RouterLink>
  </div>
  <div class="info-banner">
    <Icon name="database" /><span
      >当前预览本地治理数据集；数据库采集的原始快照可在“本地原始库”查看。</span
    >
  </div>
  <section class="panel">
    <div class="table-toolbar">
      <label class="inline-label"
        >选择数据集<select v-model="selected" @change="changeDataset">
          <option v-for="d in platform.datasets" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select></label
      ><span>{{ total }} 条记录 · {{ columns.length }} 个字段</span>
    </div>
    <div class="field-chips">
      <span v-for="c in columns" :key="c.key"><Icon name="standard" :size="13" />{{ c.key }}</span>
    </div>
    <DataTable :rows="rows" :columns="columns" :loading="busy" empty="当前数据集没有记录" />
    <div class="pagination">
      <span>第 {{ page }} 页</span
      ><button :disabled="page <= 1" @click="changePage(-1)">上一页</button
      ><button :disabled="page * 20 >= total" @click="changePage(1)">下一页</button>
    </div>
  </section>
</template>
