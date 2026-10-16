<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request } from '../api/client'
import type { Page, Entity } from '../api/client'
import { act, dateText, platform } from '../stores/platform'
import DataTable from '../components/DataTable.vue'
import Icon from '../components/Icon.vue'
const rows = ref<Entity[]>([]),
  page = ref(1),
  total = ref(0)
async function load() {
  const data = await request<Page>('audit?pageSize=30&pageNum=' + page.value)
  rows.value = data.list
  total.value = data.total
}
onMounted(() => {
  if (platform.user?.role === 'admin') act(load)
})
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
      <h1>操作审计</h1>
      <p>配置修改、流程运行、预警处理和服务查询均记录到本地审计文件。</p>
    </div>
    <button v-if="platform.user?.role === 'admin'" @click="act(load)">
      <Icon name="refresh" />刷新
    </button>
  </div>
  <section class="panel">
    <div v-if="platform.user?.role !== 'admin'" class="empty">此页面需要管理员权限。</div>
    <template v-else
      ><DataTable
        :rows="rows"
        :columns="[
          { key: 'actor', label: '操作人' },
          { key: 'action', label: '操作' },
          { key: 'target', label: '对象ID' },
          { key: 'createdAt', label: '时间' },
        ]"
        empty="暂无审计记录"
        ><template #createdAt="{ row }">{{ dateText(row.createdAt) }}</template></DataTable
      >
      <div class="pagination">
        <span>共 {{ total }} 条 · 第 {{ page }} 页</span
        ><button :disabled="page <= 1" @click="changePage(-1)">上一页</button
        ><button :disabled="page * 30 >= total" @click="changePage(1)">下一页</button>
      </div></template
    >
  </section>
</template>
