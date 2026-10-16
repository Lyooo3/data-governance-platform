<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { request } from '../api/client'
import type { Entity, Page } from '../api/client'
import { act, dateText, notify, platform, refresh, statusText } from '../stores/platform'
import DataTable from '../components/DataTable.vue'
import Icon from '../components/Icon.vue'
const route = useRoute(),
  router = useRouter(),
  runs = ref<Entity[]>([]),
  selected = ref(String(route.query.run || '')),
  run = ref<Entity>(),
  rows = ref<Entity[]>([]),
  total = ref(0),
  page = ref(1)
const loading = ref(true)
const columns = computed(() => Object.keys(rows.value[0] || {}).map((k) => ({ key: k, label: k })))
let timer: ReturnType<typeof setTimeout> | undefined,
  stopped = false
async function load() {
  loading.value = true
  try {
    const values = await request<Page>('runs?pageSize=500')
    runs.value = values.list
    if (!selected.value && values.list.length) selected.value = values.list[0]!.id
    if (selected.value) await detail()
    await refresh()
  } finally {
    loading.value = false
  }
}
async function detail() {
  if (!selected.value) return
  run.value = await request('runs/' + selected.value)
  const result = await request<Page>(
    'runs/' + selected.value + '/rows?pageSize=20&pageNum=' + page.value,
  )
  rows.value = result.list
  total.value = result.total
  if (timer) clearTimeout(timer)
  if (run.value?.status === 'RUNNING' && !stopped)
    timer = setTimeout(() => {
      act(load)
    }, 1000)
}
onMounted(() => act(load))
onUnmounted(() => {
  stopped = true
  clearTimeout(timer)
})
async function choose() {
  page.value = 1
  await act(detail)
  router.replace({ query: { run: selected.value } })
}
async function cancel() {
  await act(async () => {
    await request('runs/' + selected.value + '/cancel', 'POST', {})
    notify('任务已取消')
    await load()
  })
}
function changePage(delta: number) {
  page.value += delta
  act(detail)
}
function changeDataset() {
  page.value = 1
  act(detail)
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>运行与报告</h1>
      <p>真实执行状态、处理步骤、质量报告与结果数据。</p>
    </div>
    <button @click="act(load)"><Icon name="refresh" />刷新</button>
  </div>
  <section class="panel">
    <div class="table-toolbar">
      <label class="inline-label"
        >运行记录<select v-model="selected" aria-label="选择运行记录" @change="choose">
          <option v-for="r in runs" :key="r.id" :value="r.id">
            {{ r.name }} · {{ dateText(r.startedAt) }}
          </option>
        </select></label
      ><span class="muted">共 {{ runs.length }} 次运行</span>
    </div>
    <div v-if="!run" class="empty">
      <Icon name="flow" :size="35" /><strong>{{
        loading ? '正在读取运行记录…' : '暂无运行记录'
      }}</strong>
      <p v-if="!loading">在治理流程中执行样例，或在自定义质量中执行检测任务。</p>
      <RouterLink v-if="!loading" to="/develop/flows" class="primary button"
        >打开治理流程 →</RouterLink
      >
    </div>
    <template v-else
      ><div class="run-heading">
        <div>
          <h2>{{ run.name }}</h2>
          <p class="muted">{{ dateText(run.startedAt) }} · {{ run.actor }}</p>
        </div>
        <span :class="['badge', run.status]">{{ statusText[run.status] }}</span
        ><button
          v-if="run.status === 'RUNNING' && platform.user?.role === 'admin'"
          class="danger"
          @click="cancel"
        >
          取消执行</button
        ><a
          v-if="run.status === 'SUCCESS'"
          :href="'/api/governance/runs/' + run.id + '/export'"
          class="button primary"
          >下载CSV</a
        >
      </div>
      <div v-if="run.error" class="error-banner">{{ run.error }}</div>
      <div class="run-numbers">
        <div>
          <small>输入记录</small><strong>{{ run.sourceCount ?? '—' }}</strong>
        </div>
        <div>
          <small>输出记录</small><strong>{{ run.outputCount ?? '—' }}</strong>
        </div>
        <div>
          <small>质量节点</small><strong>{{ run.reports.length }}</strong>
        </div>
        <div>
          <small>运行状态</small><strong class="status-number">{{ statusText[run.status] }}</strong>
        </div>
      </div>
      <h3 class="subheading">处理步骤</h3>
      <div v-if="run.status === 'RUNNING'" class="info-banner">
        <span class="spinner" />任务正在独立进程中执行，完成后展示各节点实际计数。
      </div>
      <DataTable
        v-else
        :rows="run.steps"
        :columns="[
          { key: 'name', label: '步骤' },
          { key: 'type', label: '节点类型' },
          { key: 'inputCount', label: '输入数' },
          { key: 'outputCount', label: '输出数' },
        ]"
        empty="本次未生成处理步骤"
    /></template>
  </section>
  <template v-if="run"
    ><section v-for="report in run.reports" :key="report.nodeId" class="panel">
      <h2 class="panel-title">{{ report.nodeName }} · 质量报告<span>QUALITY</span></h2>
      <div class="report-summary">
        <span>检测 {{ report.total }} 条</span
        ><span
          >问题 <b class="red">{{ report.invalidRows }}</b> 条</span
        ><span
          >合格率 <b>{{ report.passRate ?? '—' }}{{ report.passRate == null ? '' : '%' }}</b></span
        ><RouterLink to="/quality/alerts">查看预警 →</RouterLink>
      </div>
      <DataTable
        :rows="report.rules"
        :columns="[
          { key: 'name', label: '规则' },
          { key: 'field', label: '字段' },
          { key: 'total', label: '检测数' },
          { key: 'passed', label: '通过数' },
          { key: 'failed', label: '问题数' },
        ]"
      />
    </section>
    <section class="panel">
      <h2 class="panel-title">
        治理结果预览<span>{{ total }} ROWS</span>
      </h2>
      <DataTable :rows="rows" :columns="columns" empty="本次暂无输出记录" />
      <div class="pagination">
        <span>共 {{ total }} 条 · 第 {{ page }} 页</span
        ><button :disabled="page <= 1" @click="changePage(-1)">上一页</button
        ><button :disabled="page * 20 >= total" @click="changePage(1)">下一页</button>
      </div>
    </section></template
  >
</template>
