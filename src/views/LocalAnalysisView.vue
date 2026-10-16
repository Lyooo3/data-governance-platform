<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { Entity } from '../api/client'
import { platform, dateText } from '../stores/platform'
import { local, parseJson } from '../local/shared'
import LocalResult from '../components/LocalResult.vue'
const route = useRoute()
const definitions: Record<string, Entity> = {
  '/standard/benchmark': {
    op: 'standard',
    note: '对比本地数据字段与数据元标准，检查字段存在性及实际值类型。',
    action: '执行标准对标',
  },
  '/standard/code-benchmark': {
    op: 'code',
    note: '将数据字段与代码集逐条比对，可将代码名称转换为新的本地数据集。',
    action: '执行代码对标',
  },
  '/quality/timeliness': {
    op: 'timeliness',
    note: '按时间字段和最大允许间隔，识别超期、未来时间及无效时间。无时区的时间按北京时间处理。',
    action: '执行时效检查',
  },
  '/analysis/relations': {
    op: 'relations',
    note: '从两个字段生成有向关系，统计对象数量、关系数量和重复关系频次。',
    action: '执行关系分析',
  },
  '/analysis/funds': {
    op: 'funds',
    note: '按来源、去向和金额字段汇总流入、流出和净额；结果为本地数据的描述统计。',
    action: '执行资金统计',
  },
  '/service/operations': {
    op: 'operate',
    note: '执行清洗、过滤、去重或字段映射，生成新的本地数据集，保留原数据。',
    action: '执行数据操作',
  },
}
const config = definitions[route.path]!
const boot = ref<Entity>({ datasets: [], elements: [], dictionaries: [] }),
  history = ref<Entity[]>([]),
  selected = ref(''),
  result = ref<Entity>(),
  error = ref(''),
  busy = ref(false)
const form = ref<Entity>({
  name: '',
  datasetId: '',
  field: '',
  dictionaryId: '',
  apply: false,
  outputField: '',
  mappingText: '{}',
  maxAgeHours: 24,
  referenceTime: '',
  fromField: '',
  toField: '',
  amountField: '',
  action: 'clean',
  configText: '{}',
})
const fields = computed<string[]>(
  () => boot.value.datasets.find((d: Entity) => d.id === form.value.datasetId)?.fields || [],
)
const canWrite = computed(() => platform.user?.role === 'admin')
function defaults() {
  form.value.field = fields.value[0] || ''
  form.value.fromField = fields.value[0] || ''
  form.value.toField = fields.value[1] || ''
  form.value.amountField =
    fields.value.find((f) => ['amount', 'score', '金额'].includes(f)) || fields.value[2] || ''
  operationDefaults()
}
function operationDefaults() {
  const field = fields.value[0] || ''
  form.value.configText = JSON.stringify(
    form.value.action === 'select'
      ? { mappings: fields.value.map((f) => ({ from: f, to: f })) }
      : form.value.action === 'filter'
        ? { field, operator: 'eq', value: '' }
        : form.value.action === 'dedupe'
          ? { fields: [field] }
          : { fields: [field], operation: 'trim' },
    null,
    2,
  )
}
watch(() => form.value.datasetId, defaults)
watch(() => form.value.action, operationDefaults)
async function load() {
  try {
    const [data, reports] = await Promise.all([
      local('bootstrap'),
      local('records/reports?operation=' + config.op),
    ])
    boot.value = data
    history.value = reports.list
    form.value.datasetId ||= data.datasets[0]?.id || ''
    form.value.dictionaryId ||= data.dictionaries[0]?.id || ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  }
}
onMounted(load)
async function execute() {
  busy.value = true
  error.value = ''
  try {
    const body: Entity = {
      ...form.value,
      mapping: parseJson(form.value.mappingText, '字段映射'),
      config: parseJson(form.value.configText, '操作参数'),
    }
    if (!body.referenceTime) delete body.referenceTime
    result.value = await local('analyze/' + config.op, 'POST', body)
    selected.value = result.value!.id
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '执行失败'
  } finally {
    busy.value = false
  }
}
async function choose() {
  if (!selected.value) return
  try {
    result.value = await local('records/reports/' + selected.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  }
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>{{ route.meta.title }}</h1>
      <p>{{ config.note }}</p>
    </div>
    <button @click="load">刷新</button>
  </div>
  <section class="panel local-config-panel">
    <div class="local-section-head">
      <h2>分析配置</h2>
      <span class="badge">本地数据</span>
    </div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <form @submit.prevent="execute">
      <div class="form-grid">
        <label
          >报告或结果名称<input
            v-model="form.name"
            maxlength="120"
            placeholder="留空使用自动名称"
            :disabled="!canWrite"
        /></label>
        <label
          >数据集<select v-model="form.datasetId" required :disabled="!canWrite">
            <option v-for="d in boot.datasets" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select></label
        >
        <template v-if="config.op === 'standard'"
          ><label class="full-width"
            >字段映射（标准字段:数据字段）<textarea
              v-model="form.mappingText"
              rows="4"
              :disabled="!canWrite"
            />
          </label>
          <p class="muted full-width">
            将使用数据标准模块中的数据元。未配置映射时按字段标识匹配。
          </p></template
        >
        <template v-if="['code', 'timeliness'].includes(config.op)"
          ><label
            >检查字段<select v-model="form.field" required :disabled="!canWrite">
              <option v-for="f in fields" :key="f" :value="f">{{ f }}</option>
            </select></label
          ></template
        >
        <template v-if="config.op === 'code'"
          ><label
            >标准代码集<select v-model="form.dictionaryId" required :disabled="!canWrite">
              <option v-for="d in boot.dictionaries" :key="d.id" :value="d.id">{{ d.name }}</option>
            </select></label
          ><label class="checkbox-label"
            ><input
              v-model="form.apply"
              type="checkbox"
              :disabled="!canWrite"
            />生成转换数据集</label
          ><label v-if="form.apply"
            >输出名称字段<input
              v-model="form.outputField"
              placeholder="留空使用原字段_name"
              :disabled="!canWrite" /></label
        ></template>
        <template v-if="config.op === 'timeliness'"
          ><label
            >最大允许间隔（小时）<input
              v-model.number="form.maxAgeHours"
              type="number"
              min="0.001"
              step="any"
              required
              :disabled="!canWrite" /></label
          ><label
            >检查基准时间<input
              v-model="form.referenceTime"
              placeholder="留空使用当前时间，可填ISO时间"
              :disabled="!canWrite" /></label
        ></template>
        <template v-if="['relations', 'funds'].includes(config.op)"
          ><label
            >来源字段<select v-model="form.fromField" required :disabled="!canWrite">
              <option v-for="f in fields" :key="f" :value="f">{{ f }}</option>
            </select></label
          ><label
            >去向字段<select v-model="form.toField" required :disabled="!canWrite">
              <option v-for="f in fields" :key="f" :value="f">{{ f }}</option>
            </select></label
          ><label v-if="config.op === 'funds'"
            >金额字段<select v-model="form.amountField" required :disabled="!canWrite">
              <option v-for="f in fields" :key="f" :value="f">{{ f }}</option>
            </select></label
          ></template
        >
        <template v-if="config.op === 'operate'"
          ><label
            >操作类型<select v-model="form.action" :disabled="!canWrite">
              <option value="clean">字段清洗</option>
              <option value="filter">条件过滤</option>
              <option value="dedupe">业务键去重</option>
              <option value="select">字段映射</option>
            </select></label
          ><label class="full-width"
            >操作参数（JSON对象）<textarea
              v-model="form.configText"
              rows="8"
              :disabled="!canWrite"
            /></label
        ></template>
      </div>
      <div class="modal-actions">
        <span v-if="!canWrite" class="muted">只读账号可查看历史报告。</span
        ><button v-else class="primary" type="submit" :disabled="busy || !form.datasetId">
          {{ busy ? '正在执行…' : config.action }}
        </button>
      </div>
    </form>
  </section>
  <section class="panel">
    <label class="inline-label"
      >历史报告<select v-model="selected" @change="choose">
        <option value="">选择报告</option>
        <option v-for="r in history" :key="r.id" :value="r.id">
          {{ r.name }} · {{ dateText(r.createdAt) }}
        </option>
      </select></label
    >
    <p v-if="!history.length" class="muted">暂无报告，执行后配置与结果会保存到平台。</p>
  </section>
  <LocalResult :value="result" />
</template>
