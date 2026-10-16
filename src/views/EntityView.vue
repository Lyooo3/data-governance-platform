<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { list, remove, request, save } from '../api/client'
import type { Entity } from '../api/client'
import { act, dateText, notify, platform, refresh } from '../stores/platform'
import DataTable from '../components/DataTable.vue'
import Modal from '../components/Modal.vue'
import Icon from '../components/Icon.vue'
const route = useRoute(),
  router = useRouter(),
  kind = String((route.meta.page as Entity).kind)
const typeNames: Record<string, string> = {
  required: '非空',
  unique: '唯一性',
  range: '数值范围',
  regex: '正则格式',
  enum: '允许值',
  mysql: 'MySQL',
  postgresql: 'PostgreSQL',
}
const kindName =
  (
    {
      sources: '接入草稿',
      datasets: '数据集',
      rules: '质量规则',
      qualityTasks: '检测任务',
      services: '数据服务',
      assets: '数据资源',
      elements: '数据元',
      dictionaries: '代码集',
      qualifiers: '限定词',
      businessTypes: '业务分类',
      catalogs: '目录',
      projects: '项目',
      tables: '元数据配置',
      alertPolicies: '预警配置',
    } as Record<string, string>
  )[kind] || '配置'
const rows = ref<Entity[]>([]),
  search = ref(''),
  pageNum = ref(1),
  busy = ref(false),
  opened = ref(false),
  editing = ref<Entity>({}),
  saving = ref(false),
  deleteItem = ref<Entity>(),
  published = ref<Entity>(),
  error = ref(''),
  formError = ref(''),
  deleteError = ref('')
const canWrite = computed(() => platform.user?.role === 'admin')
const filtered = computed(() =>
  rows.value.filter((r) => JSON.stringify(r).toLowerCase().includes(search.value.toLowerCase())),
)
const pageRows = computed(() => filtered.value.slice((pageNum.value - 1) * 10, pageNum.value * 10))
watch(
  () => filtered.value.length,
  (count) => {
    pageNum.value = Math.min(pageNum.value, Math.max(1, Math.ceil(count / 10)))
  },
)
type FormField = {
  key: string
  label: string
  type?: string
  options?: { value: string; label: string }[]
  hint?: string
}
const fields = computed<FormField[]>(() => {
  const base: FormField[] = [{ key: 'name', label: '名称' }]
  const coded = [
    { key: 'code', label: '编号' },
    { key: 'version', label: '版本' },
  ]
  const dataset = {
    key: 'datasetId',
    label: '关联数据集',
    type: 'select',
    options: platform.datasets.map((d) => ({ value: d.id, label: d.name })),
  }
  if (kind === 'sources')
    return [
      ...base,
      {
        key: 'type',
        label: '数据库类型',
        type: 'select',
        options: [
          { value: 'mysql', label: 'MySQL' },
          { value: 'postgresql', label: 'PostgreSQL' },
        ],
      },
      { key: 'host', label: '主机地址（预留）' },
      { key: 'port', label: '端口（预留）', type: 'number' },
      { key: 'database', label: '数据库名称（预留）' },
      { key: 'user', label: '账号（预留）' },
      {
        key: 'description',
        label: '说明',
        type: 'textarea',
        hint: '当前只保存接入草稿，不保存密码、不测试连接。',
      },
    ]
  if (kind === 'rules')
    return [
      ...base,
      { key: 'field', label: '检查字段' },
      {
        key: 'type',
        label: '规则类型',
        type: 'select',
        options: [
          { value: 'required', label: '非空' },
          { value: 'unique', label: '唯一且非空' },
          { value: 'range', label: '数值范围' },
          { value: 'regex', label: '正则格式' },
          { value: 'enum', label: '允许值集合' },
        ],
      },
      ...(editing.value.type === 'range'
        ? [
            { key: 'min', label: '最小值', type: 'number' },
            { key: 'max', label: '最大值', type: 'number' },
          ]
        : editing.value.type === 'regex'
          ? [{ key: 'pattern', label: '正则表达式' }]
          : editing.value.type === 'enum'
            ? [{ key: 'valuesText', label: '允许值（逗号分隔）' }]
            : []),
    ]
  if (kind === 'datasets')
    return [
      ...base,
      { key: 'description', label: '说明' },
      {
        key: 'rowsText',
        label: '数据记录（JSON对象数组）',
        type: 'textarea',
        hint: '最多10,000行，每行字段必须一致，不连接数据库。',
      },
    ]
  if (kind === 'qualityTasks')
    return [...base, dataset, { key: 'ruleIds', label: '检测规则', type: 'rules' }]
  if (kind === 'services')
    return [
      ...base,
      {
        key: 'sourceMode',
        label: '数据来源',
        type: 'select',
        options: [
          { value: 'dataset', label: '本地数据集' },
          { value: 'run', label: '成功运行结果' },
          { value: 'view', label: '本地视图' },
        ],
      },
      ...(editing.value.sourceMode === 'dataset' ? [dataset] : []),
      ...(editing.value.sourceMode === 'run'
        ? [
            {
              key: 'runId',
              label: '关联成功运行',
              type: 'select',
              options: [
                ...platform.runs
                  .filter((r) => r.status === 'SUCCESS')
                  .map((r) => ({ value: r.id, label: r.name + ' / ' + dateText(r.startedAt) })),
              ],
            },
          ]
        : []),
      ...(editing.value.sourceMode === 'view'
        ? [
            {
              key: 'viewId',
              label: '关联本地视图',
              type: 'select',
              options: platform.views.map((v) => ({ value: v.id, label: v.name })),
            },
          ]
        : []),
      { key: 'fieldsText', label: '查询字段（逗号分隔，留空为全部）' },
      { key: 'description', label: '服务说明', type: 'textarea' },
    ]
  if (kind === 'assets')
    return [
      ...base,
      dataset,
      { key: 'dataLevelName', label: '数据级别' },
      { key: 'sourceSystem', label: '来源系统' },
      { key: 'region', label: '来源地区' },
      { key: 'catalogId', label: '目录ID（可选）' },
      { key: 'description', label: '说明', type: 'textarea' },
    ]
  if (kind === 'elements')
    return [
      ...base,
      ...coded,
      { key: 'field', label: '字段标识' },
      { key: 'dataType', label: '数据类型' },
      { key: 'description', label: '业务含义', type: 'textarea' },
    ]
  if (kind === 'dictionaries')
    return [
      ...base,
      ...coded,
      { key: 'dictionaryText', label: '代码项（每行 代码:名称）', type: 'textarea' },
    ]
  if (kind === 'tables')
    return [
      ...base,
      dataset,
      { key: 'columnsText', label: '字段结构（JSON数组）', type: 'textarea' },
    ]
  if (kind === 'alertPolicies')
    return [
      ...base,
      {
        key: 'severity',
        label: '预警级别',
        type: 'select',
        options: [
          { value: 'normal', label: '一般' },
          { value: 'high', label: '重要' },
        ],
      },
      {
        key: 'description',
        label: '处理要求',
        type: 'textarea',
        hint: '保存管理说明；外部通知和定时策略尚未启用。',
      },
    ]
  return [...base, ...coded, { key: 'description', label: '说明', type: 'textarea' }]
})
const columns = computed(() => [
  { key: 'name', label: '名称' },
  ...(kind === 'sources'
    ? [
        { key: 'type', label: '类型' },
        { key: 'host', label: '主机地址' },
        { key: 'status', label: '状态' },
      ]
    : kind === 'rules'
      ? [
          { key: 'field', label: '检查字段' },
          { key: 'type', label: '规则类型' },
        ]
      : kind === 'datasets'
        ? [
            { key: 'rowCount', label: '记录数' },
            { key: 'description', label: '说明' },
          ]
        : kind === 'services'
          ? [
              { key: 'datasetId', label: '数据关联' },
              { key: 'published', label: '发布状态' },
            ]
          : kind === 'qualityTasks'
            ? [
                { key: 'datasetId', label: '数据集' },
                { key: 'ruleIds', label: '规则数' },
              ]
            : [
                { key: 'code', label: '编号' },
                { key: 'description', label: '说明' },
              ]),
  { key: 'updatedAt', label: '更新时间' },
])
async function load() {
  busy.value = true
  error.value = ''
  try {
    rows.value = (await list(kind)).list
    await refresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
async function edit(item?: Entity) {
  formError.value = ''
  await act(async () => {
    const record = item ? await request<Entity>(kind + '/' + item.id) : {}
    editing.value = {
      name: '',
      version: '1.0',
      type: kind === 'sources' ? 'mysql' : 'required',
      port: 3306,
      datasetId: platform.datasets[0]?.id,
      ruleIds: [],
      ...record,
      sourceMode: record.viewId ? 'view' : record.runId ? 'run' : 'dataset',
      rowsText: JSON.stringify(record.rows || [], null, 2),
      valuesText: (record.values || []).join(','),
      fieldsText: (record.fields || []).join(','),
      dictionaryText: (record.dictionaryDetails || [])
        .map((d: Entity) => d.code + ':' + d.name)
        .join('\n'),
      columnsText: JSON.stringify(record.columns || [], null, 2),
    }
    opened.value = true
  })
}
async function submit() {
  saving.value = true
  formError.value = ''
  try {
    const value = { ...editing.value }
    if (kind === 'rules') {
      value.values = String(value.valuesText || '')
        .split(/[,，]/)
        .map((s) => s.trim())
        .filter(Boolean)
      for (const k of ['min', 'max'])
        value[k] = value[k] === '' || value[k] == null ? null : Number(value[k])
    }
    if (kind === 'datasets') value.rows = parseArray(value.rowsText, '数据记录')
    if (kind === 'services') {
      value.fields = String(value.fieldsText)
        .split(/[,，]/)
        .map((s) => s.trim())
        .filter(Boolean)
      if (value.sourceMode !== 'dataset') value.datasetId = ''
      if (value.sourceMode !== 'run') value.runId = ''
      if (value.sourceMode !== 'view') value.viewId = ''
    }
    if (kind === 'tables') value.columns = parseArray(value.columnsText, '字段结构')
    if (kind === 'dictionaries')
      value.dictionaryDetails = String(value.dictionaryText)
        .split('\n')
        .filter(Boolean)
        .map((line) => {
          const [code, ...rest] = line.split(':')
          return { code: code?.trim(), name: rest.join(':').trim() }
        })
    for (const k of Object.keys(value)) if (k.endsWith('Text')) delete value[k]
    await save(kind, value)
    opened.value = false
    await load()
    notify('配置已保存')
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '保存失败，请检查配置'
  } finally {
    saving.value = false
  }
}
function parseArray(text: string, label: string) {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    throw new Error(`${label}不是有效的JSON，请检查双引号、逗号和括号。`)
  }
  if (!Array.isArray(value)) throw new Error(`${label}必须是JSON数组，使用 [ ] 包含记录。`)
  return value
}
function confirmDelete(item: Entity) {
  deleteError.value = ''
  deleteItem.value = item
}
async function erase() {
  if (!deleteItem.value) return
  deleteError.value = ''
  try {
    await remove(kind, deleteItem.value!.id)
    deleteItem.value = undefined
    await load()
    notify('配置已删除')
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : '删除失败'
  }
}
async function run(item: Entity) {
  await act(async () => {
    const value = await request('qualityTasks/' + item.id + '/run', 'POST', {})
    router.push('/develop/runs?run=' + value.id)
  })
}
async function publish(item: Entity) {
  await act(async () => {
    published.value = await request('services/' + item.id + '/publish', 'POST', {})
    await load()
    notify('服务已发布，请保存本次密钥')
  })
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>{{ route.meta.title }}</h1>
      <p>{{ (route.meta.page as Entity).description || '统一维护配置，保存后即时生效。' }}</p>
    </div>
    <button v-if="canWrite" class="primary" @click="edit()">
      <Icon name="plus" />{{ '新增' + kindName }}
    </button>
  </div>
  <div v-if="kind === 'sources'" class="info-banner">
    <Icon name="database" />
    <div>
      <strong>业务数据库暂不配置</strong>
      <p>当前可保存接入草稿，不会建立连接或保存密码。流程可使用内置样例和导入的JSON数据集。</p>
    </div>
    <RouterLink to="/access/datasets">管理样例 →</RouterLink>
  </div>
  <section class="panel">
    <div class="table-toolbar">
      <div class="search-field">
        <Icon name="search" /><input
          v-model="search"
          aria-label="搜索记录"
          placeholder="搜索名称、编号或字段"
          @input="pageNum = 1"
        />
      </div>
      <span class="muted">共 {{ filtered.length }} 条</span
      ><button @click="load"><Icon name="refresh" />刷新</button>
    </div>
    <div v-if="error" class="error-banner">{{ error }} <button @click="load">重新读取</button></div>
    <DataTable :rows="pageRows" :columns="columns" :loading="busy"
      ><template #updatedAt="{ row }">{{ dateText(row.updatedAt) }}</template
      ><template #ruleIds="{ row }">{{ row.ruleIds?.length || 0 }}</template
      ><template #datasetId="{ row }">{{
        row.viewId
          ? '本地视图：' + (platform.views.find((v) => v.id === row.viewId)?.name || '—')
          : row.runId
            ? '治理运行结果'
            : platform.datasets.find((d) => d.id === row.datasetId)?.name || '—'
      }}</template
      ><template #type="{ row }">{{ typeNames[row.type] || row.type }}</template
      ><template #status="{ row }"
        ><span class="badge draft">{{
          row.status === 'draft' ? '尚未连接' : row.status
        }}</span></template
      ><template #published="{ row }"
        ><span :class="['badge', row.published ? 'SUCCESS' : 'draft']">{{
          row.published ? '已发布' : '未发布'
        }}</span></template
      ><template #actions="{ row }"
        ><button
          v-if="kind === 'datasets'"
          class="text-button"
          @click="router.push('/access/preview?dataset=' + row.id)"
        >
          预览</button
        ><template v-if="canWrite"
          ><button class="text-button" @click="edit(row)">编辑</button
          ><button v-if="kind === 'qualityTasks'" class="text-button" @click="run(row)">
            执行检测</button
          ><button v-if="kind === 'services'" class="text-button" @click="publish(row)">
            {{ row.published ? '重新发布' : '发布' }}</button
          ><button class="text-button red" @click="confirmDelete(row)">删除</button></template
        ><span v-else class="muted">只读</span></template
      ></DataTable
    >
    <div class="pagination">
      <span>第 {{ pageNum }} / {{ Math.max(1, Math.ceil(filtered.length / 10)) }} 页</span
      ><button :disabled="pageNum <= 1" @click="pageNum--">上一页</button
      ><button :disabled="pageNum * 10 >= filtered.length" @click="pageNum++">下一页</button>
    </div>
  </section>
  <Modal
    :open="opened"
    :title="(editing.id ? '编辑' : '新增') + kindName"
    :wide="kind === 'datasets'"
    @close="opened = false"
    ><form @submit.prevent="submit">
      <p v-if="formError" class="error-banner" role="alert">{{ formError }}</p>
      <div class="form-grid">
        <label
          v-for="f in fields"
          :key="f.key"
          :class="{ 'full-width': ['textarea', 'rules'].includes(f.type || '') }"
          ><span>{{ f.label }}</span
          ><select v-if="f.type === 'select'" v-model="editing[f.key]">
            <option v-for="o in f.options" :key="o.value" :value="o.value">
              {{ o.label }}
            </option></select
          ><textarea
            v-else-if="f.type === 'textarea'"
            v-model="editing[f.key]"
            :rows="f.key === 'rowsText' ? 13 : 4"
            :class="{ mono: f.key.endsWith('Text') }"
          />
          <div v-else-if="f.type === 'rules'" class="rule-options">
            <label v-for="r in platform.rules" :key="r.id"
              ><input v-model="editing.ruleIds" type="checkbox" :value="r.id" />{{ r.name }}</label
            >
          </div>
          <input
            v-else
            v-model="editing[f.key]"
            :type="f.type || 'text'"
            :step="f.type === 'number' ? (f.key === 'port' ? 1 : 'any') : undefined"
            :required="f.key === 'name' || f.key === 'field'"
            :maxlength="f.type === 'number' ? undefined : f.key === 'name' ? 120 : 200"
          /><small v-if="f.hint" class="muted">{{ f.hint }}</small></label
        >
      </div>
      <div class="modal-actions">
        <button type="button" @click="opened = false">取消</button
        ><button type="submit" class="primary" :disabled="saving">
          {{ saving ? '保存中…' : '保存配置' }}
        </button>
      </div>
    </form></Modal
  >
  <Modal :open="!!deleteItem" title="删除配置" @close="deleteItem = undefined"
    ><p>确认删除“{{ deleteItem?.name }}”？被引用的关键配置会由后端阻止删除。</p>
    <p v-if="deleteError" class="error-banner" role="alert">{{ deleteError }}</p>
    <div class="modal-actions">
      <button @click="deleteItem = undefined">取消</button
      ><button class="danger" @click="erase">确认删除</button>
    </div></Modal
  >
  <Modal :open="!!published" title="数据服务已发布" @close="published = undefined"
    ><p>查询地址</p>
    <code class="code-block">{{ published?.endpoint }}</code>
    <p>使用 X-API-Key 请求头传入以下密钥。密钥仅本次显示，重新发布会使旧密钥失效。</p>
    <code class="code-block">{{ published?.apiKey }}</code>
    <div class="modal-actions">
      <button class="primary" @click="published = undefined">已保存密钥</button>
    </div></Modal
  >
</template>
