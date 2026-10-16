<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { request, type Entity } from '../api/client'
import { platform, refresh, dateText } from '../stores/platform'
import DataTable from '../components/DataTable.vue'
const route = useRoute(),
  snapshots = ref<Entity[]>([]),
  selected = ref(String(route.query.snapshot || '')),
  snapshot = ref<Entity>(),
  tableId = ref(''),
  search = ref(''),
  rows = ref<Entity[]>([]),
  page = ref(1),
  mode = ref('fields'),
  error = ref(''),
  busy = ref(false),
  fields = ref<string[]>([]),
  name = ref(''),
  offset = ref(0),
  limit = ref(10000),
  result = ref<Entity>()
const table = computed<Entity | undefined>(() =>
  snapshot.value?.tables.find((t: Entity) => t.id === tableId.value),
)
const filtered = computed<Entity[]>(
  () =>
    snapshot.value?.tables.filter((t: Entity) =>
      (t.schema + '.' + t.name).toLowerCase().includes(search.value.toLowerCase()),
    ) || [],
)
const rowColumns = computed(() =>
  Object.keys(rows.value[0] || {}).map((key) => ({ key, label: key })),
)
const count = computed(() =>
  Math.max(0, Math.min(limit.value, (table.value?.rowCount || 0) - offset.value)),
)
const complete = computed(
  () =>
    offset.value === 0 &&
    count.value === table.value?.rowCount &&
    fields.value.length === table.value?.columns.length,
)
watch(filtered, (options) => {
  if (!options.some((t) => t.id === tableId.value)) {
    tableId.value = options[0]?.id || ''
    if (tableId.value) chooseTable()
    else {
      rows.value = []
      fields.value = []
      result.value = undefined
    }
  }
})
async function load() {
  if (platform.user?.role !== 'admin') return
  try {
    snapshots.value = (await request('/api/ingestion/snapshots')).list.filter(
      (s: Entity) => s.status === 'SUCCESS',
    )
    selected.value ||= snapshots.value[0]?.id || ''
    if (selected.value) await chooseSnapshot()
  } catch (e) {
    error.value = (e as Error).message
  }
}
async function chooseSnapshot() {
  error.value = ''
  result.value = undefined
  try {
    snapshot.value = await request('/api/ingestion/snapshots/' + selected.value)
    tableId.value = snapshot.value!.tables[0]?.id || ''
    if (tableId.value) await chooseTable()
  } catch (e) {
    error.value = (e as Error).message
  }
}
async function chooseTable() {
  page.value = 1
  rows.value = []
  fields.value = table.value?.columns.slice(0, 100).map((c: Entity) => c.name) || []
  name.value = table.value ? table.value.schema + '.' + table.value.name + '-治理副本' : ''
  offset.value = 0
  limit.value = Math.min(10000, table.value?.rowCount || 10000)
  result.value = undefined
  if (mode.value === 'rows') await loadRows()
}
async function loadRows() {
  if (!table.value) return
  busy.value = true
  error.value = ''
  try {
    rows.value = (
      await request(
        '/api/ingestion/snapshots/' +
          selected.value +
          '/tables/' +
          tableId.value +
          '/rows?pageNum=' +
          page.value +
          '&pageSize=20',
      )
    ).list
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
async function toggle(value: string) {
  mode.value = value
  if (value === 'rows') await loadRows()
}
async function changePage(delta: number) {
  page.value += delta
  await loadRows()
}
async function createCopy() {
  if (!table.value) return
  busy.value = true
  error.value = ''
  try {
    result.value = await request(
      '/api/ingestion/snapshots/' + selected.value + '/tables/' + tableId.value + '/datasets',
      'POST',
      { name: name.value, offset: offset.value, limit: limit.value, fields: fields.value },
    )
    await refresh()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>本地原始库</h1>
      <p>采集完成的只读快照保留原始值，治理副本和输出结果另存。</p>
    </div>
    <button @click="load">刷新</button>
  </div>
  <p v-if="platform.user?.role !== 'admin'" class="info-banner">原始训练数据仅管理员可访问。</p>
  <template v-else>
    <div class="info-banner">
      连接采集一次，后续浏览和治理从本机原始库读取。再次采集会生成新版本。<RouterLink
        to="/access/sources"
        >接入数据库 →</RouterLink
      >
    </div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <section class="panel">
      <label class="raw-wide-label"
        >选择本地原始库<select v-model="selected" @change="chooseSnapshot">
          <option v-if="!snapshots.length" value="">暂无已完成的原始库</option>
          <option v-for="s in snapshots" :key="s.id" :value="s.id">
            {{ s.name }} · {{ dateText(s.finishedAt) }}
          </option>
        </select></label
      >
      <div v-if="snapshot" class="local-metrics">
        <div>
          <small>来源数据库</small
          ><strong>{{ snapshot.source.database || snapshot.source.filePath || '本地文件' }}</strong>
        </div>
        <div>
          <small>已采集业务表</small><strong>{{ snapshot.tableCount }}</strong>
        </div>
        <div>
          <small>原始记录</small><strong>{{ snapshot.rowCount }}</strong>
        </div>
        <div>
          <small>采集范围</small
          ><strong>{{ snapshot.scope === 'all' ? '全部业务表' : '所选业务表' }}</strong>
        </div>
      </div>
      <template v-if="snapshot"
        ><p class="muted tiny">
          快照时间：{{ dateText(snapshot.snapshotAt) }} ·
          {{
            snapshot.transaction?.consistent_snapshot === false
              ? '尽力读取，数据可能在采集期间变化'
              : '一致只读快照'
          }}；保留类型与原值文本，不复制触发器、权限或程序。
        </p>
        <a :href="'/api/ingestion/snapshots/' + selected + '/download'" class="button"
          >下载原始库SQLite</a
        ></template
      >
    </section>
    <section v-if="snapshot" class="panel">
      <div class="table-toolbar">
        <input v-model="search" aria-label="筛选原始表" placeholder="筛选本地表名" /><span
          >共{{ filtered.length }}张表</span
        >
      </div>
      <label class="raw-wide-label"
        >原始表<select v-model="tableId" @change="chooseTable">
          <option v-for="t in filtered" :key="t.id" :value="t.id">
            {{ t.schema }}.{{ t.name }} · {{ t.rowCount }}行
          </option>
        </select></label
      >
      <template v-if="table"
        ><p>
          {{ table.columns.length }}个字段 · {{ table.rowCount }}条记录 ·
          {{ table.comment || '无表说明' }}
        </p>
        <div class="local-tabs">
          <button :class="{ primary: mode === 'fields' }" @click="toggle('fields')">字段结构</button
          ><button :class="{ primary: mode === 'rows' }" @click="toggle('rows')">原始记录</button>
        </div>
        <DataTable
          v-if="mode === 'fields'"
          :rows="table.columns"
          :columns="[
            { key: 'name', label: '字段' },
            { key: 'type', label: '原类型' },
            { key: 'primary_key', label: '主键' },
            { key: 'nullable', label: '允许空值' },
            { key: 'comment', label: '说明' },
          ]"
          ><template #primary_key="{ row }">{{ row.primary_key ? '是' : '否' }}</template
          ><template #nullable="{ row }">{{ row.nullable ? '是' : '否' }}</template></DataTable
        >
        <template v-else
          ><p class="muted tiny">
            以下显示原始文本值，SQL空值保留为空值；不会对原始库进行清洗或类型覆盖。
          </p>
          <DataTable :rows="rows" :columns="rowColumns" :loading="busy" />
          <div class="pagination">
            <span>第{{ page }} / {{ Math.max(1, Math.ceil(table.rowCount / 20)) }}页</span
            ><button :disabled="busy || page <= 1" @click="changePage(-1)">上一页</button
            ><button :disabled="busy || page * 20 >= table.rowCount" @click="changePage(1)">
              下一页
            </button>
          </div></template
        ></template
      >
    </section>
    <section v-if="table" class="panel">
      <h2>从原始表创建治理副本</h2>
      <p class="muted">
        原始库保留完整采集数据。现有治理引擎每次处理最多10,000行、100个字段；大表可按区间分批创建副本。
      </p>
      <form @submit.prevent="createCopy">
        <div class="form-grid">
          <label>副本名称<input v-model="name" required maxlength="120" /></label
          ><label
            >起始位置（从0计）<input
              v-model.number="offset"
              type="number"
              min="0"
              required /></label
          ><label
            >最多读取行数<input v-model.number="limit" type="number" min="1" max="10000" required
          /></label>
        </div>
        <div class="raw-actions">
          <button
            type="button"
            @click="fields = table.columns.slice(0, 100).map((c: Entity) => c.name)"
          >
            选择前100个字段</button
          ><button type="button" @click="fields = []">清空字段</button
          ><span>已选{{ fields.length }} / {{ table.columns.length }}个字段</span>
        </div>
        <div class="raw-field-picker">
          <label v-for="c in table.columns" :key="c.name"
            ><input v-model="fields" type="checkbox" :value="c.name" />{{ c.name }}</label
          >
        </div>
        <p class="info-banner">
          本次创建{{ count }}行、{{ fields.length }}个字段的{{
            complete ? '全表副本' : '部分副本'
          }}，来源共{{ table.rowCount }}行。原始库保持不变。
        </p>
        <button class="primary" :disabled="busy || !fields.length || fields.length > 100">
          创建治理副本
        </button>
      </form>
      <div v-if="result" class="raw-progress">
        <p class="success-banner" role="status">
          治理副本已创建：{{ result.name }} · {{ result.rowCount }}行
        </p>
        <div class="raw-actions">
          <RouterLink :to="'/access/preview?dataset=' + result.id" class="button"
            >预览治理副本</RouterLink
          ><RouterLink :to="'/develop/flows?dataset=' + result.id" class="primary button"
            >编排治理流程</RouterLink
          ><RouterLink to="/quality/rules" class="button">配置质量规则</RouterLink>
        </div>
      </div>
    </section>
  </template>
</template>
