<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Entity } from '../api/client'
import { platform, dateText } from '../stores/platform'
import { local, parseJson, commaList, downloadJson } from '../local/shared'
import DataTable from '../components/DataTable.vue'
import Modal from '../components/Modal.vue'
import LocalResult from '../components/LocalResult.vue'
const props = defineProps<{ kind: string; embedded?: boolean }>()
const route = useRoute(),
  router = useRouter()
const names: Record<string, string> = {
  schedules: '执行计划',
  views: '本地视图',
  apps: '应用',
  adapters: '接口适配',
  subscriptions: '比对订阅',
  channels: '收件通道',
}
const notes: Record<string, string> = {
  schedules: '平台运行期间按间隔执行，暂停和重启保留计划；关闭平台期间不会执行。',
  views: '通过字段白名单和条件组合查询本地数据，可作为数据服务的来源。',
  apps: '登记应用并创建凭据，只有通过服务授权后才能查询对应服务。',
  adapters: '将本地样例或接口接收数据映射为新数据集；不会向外部服务器发起请求。',
  subscriptions: '使用唯一业务键对比前后快照，发现新增、修改和删除，生成变化事件。',
  channels: '将变化事件投递到本地收件箱，可停用通道并重试失败投递。',
}
const boot = ref<Entity>({ datasets: [], workflows: [], users: [], channels: [] }),
  rows = ref<Entity[]>([]),
  search = ref(''),
  page = ref(1),
  opened = ref(false),
  form = ref<Entity>({}),
  error = ref(''),
  formError = ref(''),
  saving = ref(false),
  deleteItem = ref<Entity>(),
  deleteError = ref(''),
  detail = ref<Entity>(),
  secret = ref(''),
  result = ref<Entity>(),
  busyAction = ref('')
const canWrite = computed(() => platform.user?.role === 'admin')
const filtered = computed(() =>
  rows.value.filter((r) => JSON.stringify(r).toLowerCase().includes(search.value.toLowerCase())),
)
watch(
  () => filtered.value.length,
  (count) => (page.value = Math.min(page.value, Math.max(1, Math.ceil(count / 10)))),
)
watch(search, () => (page.value = 1))
const columns = computed(() => [
  { key: 'name', label: '名称' },
  { key: 'association', label: props.kind === 'apps' ? '归属账号' : '关联配置' },
  { key: 'state', label: '状态 / 配置' },
  { key: 'updatedAt', label: '更新时间' },
])
const displayRows = computed(() =>
  filtered.value.slice((page.value - 1) * 10, page.value * 10).map((r) => ({
    ...r,
    association:
      props.kind === 'schedules'
        ? boot.value.workflows.find((f: Entity) => f.id === r.workflowId)?.name
        : props.kind === 'apps'
          ? boot.value.users.find((u: Entity) => u.id === r.ownerId)?.name
          : props.kind === 'channels'
            ? r.recipient
            : boot.value.datasets.find((d: Entity) => d.id === r.datasetId)?.name,
    state: ['views', 'adapters'].includes(props.kind)
      ? props.kind === 'views'
        ? r.fields?.join(', ') || '全部字段'
        : r.fieldCount + ' 个映射字段'
      : (r.enabled ? '已启用' : '已暂停') +
        (['schedules', 'subscriptions'].includes(props.kind) && r.intervalSeconds
          ? ' · ' + r.intervalSeconds + '秒'
          : ''),
  })),
)
async function load() {
  try {
    error.value = ''
    const [data, list] = await Promise.all([local('bootstrap'), local('records/' + props.kind)])
    boot.value = data
    rows.value = list.list
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  }
}
function datasetChanged() {
  const fields =
    boot.value.datasets.find((d: Entity) => d.id === form.value.datasetId)?.fields || []
  form.value.fieldsText = fields.join(',')
  form.value.keysText = fields.slice(0, 1).join(',')
  form.value.mappingsText = JSON.stringify(
    fields.map((f: string) => ({ from: f, to: f })),
    null,
    2,
  )
}
onMounted(load)
async function edit(row?: Entity) {
  formError.value = ''
  form.value = {
    name: '',
    datasetId: boot.value.datasets[0]?.id || '',
    workflowId: boot.value.workflows[0]?.id || '',
    ownerId: platform.user?.id,
    recipient: '本地工作空间',
    enabled: ['apps', 'channels'].includes(props.kind),
    intervalSeconds: 300,
    maxRetries: 0,
    channelId: '',
    ...row,
  }
  const fields =
    boot.value.datasets.find((d: Entity) => d.id === form.value.datasetId)?.fields || []
  form.value.fieldsText = (row?.fields || fields).join(',')
  form.value.filtersText = JSON.stringify(row?.filters || [], null, 2)
  form.value.mappingsText = JSON.stringify(
    row?.mappings || fields.map((f: string) => ({ from: f, to: f })),
    null,
    2,
  )
  form.value.keysText = (row?.keys || fields.slice(0, 1)).join(',')
  opened.value = true
}
async function submit() {
  saving.value = true
  formError.value = ''
  try {
    const value = { ...form.value }
    if (props.kind === 'views') {
      value.fields = commaList(value.fieldsText)
      value.filters = parseJson(value.filtersText, '过滤条件')
    }
    if (props.kind === 'adapters') value.mappings = parseJson(value.mappingsText, '字段映射')
    if (props.kind === 'subscriptions') value.keys = commaList(value.keysText)
    for (const key of Object.keys(value)) if (key.endsWith('Text')) delete value[key]
    const saved = await local(
      'records/' + props.kind + (value.id ? '/' + value.id : ''),
      value.id ? 'PUT' : 'POST',
      value,
    )
    opened.value = false
    if (saved.apiKey) secret.value = saved.apiKey
    await load()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}
async function action(row: Entity, action: string) {
  error.value = ''
  busyAction.value = row.id
  try {
    const value = await local('action/' + props.kind + '/' + row.id + '/' + action, 'POST', {})
    if (value.runId) {
      await router.push('/develop/runs?run=' + value.runId)
      return
    }
    if (value.rows) result.value = value
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    busyAction.value = ''
  }
}
async function remove() {
  if (!deleteItem.value) return
  deleteError.value = ''
  try {
    await local('records/' + props.kind + '/' + deleteItem.value.id, 'DELETE')
    deleteItem.value = undefined
    await load()
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : '删除失败'
  }
}
function showDelete(row: Entity) {
  deleteError.value = ''
  deleteItem.value = row
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1 v-if="!embedded">{{ route.meta.title }}</h1>
      <h2 v-else>{{ names[kind] }}</h2>
      <p>{{ notes[kind] }}</p>
    </div>
    <button v-if="canWrite" class="primary" @click="edit()">新增{{ names[kind] }}</button>
  </div>
  <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
  <div v-if="kind === 'apps'" class="info-banner">
    <span>应用凭据创建时仅显示一次，停用应用立即阻止调用。</span
    ><RouterLink to="/service/applications">申请服务授权 →</RouterLink>
  </div>
  <div v-if="kind === 'views'" class="info-banner">
    <span>视图配置可预览，服务发布时选择“本地视图”作为数据来源。</span
    ><RouterLink to="/service/manage">发布视图服务 →</RouterLink>
  </div>
  <div v-if="kind === 'subscriptions'" class="info-banner">
    <span>新订阅会建立当前数据快照；业务键需唯一且非空。</span
    ><RouterLink to="/service/push">管理本地投递 →</RouterLink>
  </div>
  <section class="panel">
    <div class="table-toolbar">
      <input v-model="search" aria-label="搜索本地配置" placeholder="搜索配置" /><span
        >共{{ filtered.length }}条</span
      ><button @click="load">刷新</button>
    </div>
    <DataTable :rows="displayRows" :columns="columns"
      ><template #updatedAt="{ row }">{{ dateText(row.updatedAt) }}</template
      ><template #actions="{ row }"
        ><button class="text-button" @click="detail = row">详情</button
        ><template v-if="canWrite"
          ><button class="text-button" @click="edit(row)">编辑</button
          ><button
            v-if="['schedules', 'subscriptions', 'apps', 'channels'].includes(kind)"
            class="text-button"
            :disabled="busyAction === row.id"
            @click="action(row, row.enabled ? 'disable' : 'enable')"
          >
            {{ row.enabled ? '暂停' : '启用' }}</button
          ><button
            v-if="kind === 'schedules'"
            class="text-button"
            :disabled="busyAction === row.id"
            @click="action(row, 'run')"
          >
            立即执行</button
          ><button v-if="kind === 'views'" class="text-button" @click="action(row, 'preview')">
            预览视图</button
          ><button v-if="kind === 'adapters'" class="text-button" @click="action(row, 'replay')">
            测试适配</button
          ><button
            v-if="kind === 'subscriptions'"
            class="text-button"
            :disabled="busyAction === row.id"
            @click="action(row, 'compare')"
          >
            立即比对</button
          ><button class="text-button red" @click="showDelete(row)">删除</button></template
        ></template
      ></DataTable
    >
    <div class="pagination">
      <span>第{{ page }} / {{ Math.max(1, Math.ceil(filtered.length / 10)) }}页</span
      ><button :disabled="page <= 1" @click="page--">上一页</button
      ><button :disabled="page * 10 >= filtered.length" @click="page++">下一页</button>
    </div>
  </section>
  <LocalResult :value="result" />
  <Modal :open="opened" :title="(form.id ? '编辑' : '新增') + names[kind]" @close="opened = false"
    ><form @submit.prevent="submit">
      <p v-if="formError" class="error-banner" role="alert">{{ formError }}</p>
      <div class="form-grid">
        <label>名称<input v-model="form.name" required maxlength="120" /></label>
        <label v-if="['views', 'adapters', 'subscriptions'].includes(kind)"
          >数据集<select v-model="form.datasetId" required @change="datasetChanged">
            <option v-for="d in boot.datasets" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select></label
        >
        <template v-if="kind === 'schedules'"
          ><label
            >治理流程<select v-model="form.workflowId" required>
              <option v-for="f in boot.workflows" :key="f.id" :value="f.id">{{ f.name }}</option>
            </select></label
          ><label
            >失败重试次数<input
              v-model.number="form.maxRetries"
              type="number"
              min="0"
              max="3"
              required /></label
        ></template>
        <label v-if="['schedules', 'subscriptions'].includes(kind)"
          >间隔（秒）<input
            v-model.number="form.intervalSeconds"
            type="number"
            min="60"
            max="31536000"
            required
        /></label>
        <template v-if="kind === 'views'"
          ><label class="full-width"
            >字段白名单（逗号分隔）<input v-model="form.fieldsText" /></label
          ><label class="full-width"
            >过滤条件（JSON数组）<textarea
              v-model="form.filtersText"
              rows="6"
              placeholder='[{"field":"score","operator":"gt","value":80}]'
            /></label
        ></template>
        <label v-if="kind === 'apps'"
          >归属账号<select v-model="form.ownerId" required>
            <option v-for="u in boot.users" :key="u.id" :value="u.id">{{ u.name }}</option>
          </select></label
        >
        <label v-if="kind === 'adapters'" class="full-width"
          >字段映射（JSON数组）<textarea
            v-model="form.mappingsText"
            rows="8"
            placeholder='[{"from":"id","to":"record_id"}]'
          />
        </label>
        <template v-if="kind === 'subscriptions'"
          ><label>唯一业务键（逗号分隔）<input v-model="form.keysText" required /></label
          ><label
            >变化收件通道<select v-model="form.channelId">
              <option value="">仅记录变化，不自动投递</option>
              <option v-for="c in boot.channels" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select></label
          ></template
        >
        <label v-if="kind === 'channels'"
          >本地收件人<input v-model="form.recipient" required maxlength="200"
        /></label>
        <label
          v-if="['schedules', 'subscriptions', 'apps', 'channels'].includes(kind)"
          class="checkbox-label"
          ><input v-model="form.enabled" type="checkbox" />启用配置</label
        >
      </div>
      <div class="modal-actions">
        <button type="button" @click="opened = false">取消</button
        ><button class="primary" type="submit" :disabled="saving">
          {{ saving ? '保存中…' : '保存配置' }}
        </button>
      </div>
    </form></Modal
  >
  <Modal :open="!!deleteItem" title="删除本地配置" @close="deleteItem = undefined"
    ><p>确认删除“{{ deleteItem?.name }}”？仍在使用的配置会阻止删除。</p>
    <p v-if="deleteError" class="error-banner" role="alert">{{ deleteError }}</p>
    <div class="modal-actions">
      <button @click="deleteItem = undefined">取消</button
      ><button class="danger" @click="remove">确认删除</button>
    </div></Modal
  >
  <Modal :open="!!detail" title="配置详情" wide @close="detail = undefined">
    <pre class="local-json">{{ JSON.stringify(detail, null, 2) }}</pre>
    <p v-if="kind === 'adapters'">
      接收地址：/api/local/adapters/{{ detail?.id }}/receive（POST，平台管理员会话认证）
    </p>
    <div class="modal-actions">
      <button @click="downloadJson(detail, detail?.name || '配置')">下载配置</button
      ><button @click="detail = undefined">关闭详情</button>
    </div></Modal
  >
  <Modal :open="!!secret" title="应用凭据已创建" @close="secret = ''"
    ><p>调用已授权服务时，将此凭据放入 X-App-Key 请求头。凭据仅显示本次。</p>
    <code class="code-block">{{ secret }}</code>
    <div class="modal-actions">
      <button class="primary" @click="secret = ''">已保存凭据</button>
    </div></Modal
  >
</template>
