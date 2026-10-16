<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { list, request, save, remove, type Entity } from '../api/client'
import { platform, notify, dateText } from '../stores/platform'
import Modal from '../components/Modal.vue'
import DataTable from '../components/DataTable.vue'
const sources = ref<Entity[]>([]),
  snapshots = ref<Entity[]>([]),
  search = ref(''),
  error = ref(''),
  opened = ref(false),
  editing = ref<Entity>({}),
  formError = ref(''),
  saving = ref(false)
const current = ref<Entity>(),
  password = ref(''),
  actionError = ref(''),
  info = ref<Entity>(),
  tables = ref<Entity[]>([]),
  selected = ref<number[]>([]),
  tableSearch = ref(''),
  snapshotName = ref(''),
  busy = ref(false)
const canWrite = computed(() => platform.user?.role === 'admin')
const connectors = ref<Entity[]>([])
const spec = (kind: string) =>
  connectors.value.find((c) => c.type === kind) || {
    label: kind,
    passwordOptional: false,
    available: false,
    port: 5432,
  }
const currentSpec = computed(() => spec(current.value?.type || ''))
const passwordRequired = computed(() => !currentSpec.value.passwordOptional)
function typeChanged() {
  const config = spec(editing.value.type)
  editing.value.port = config.port
  editing.value.consistencyMode = config.consistency || 'strict'
  if (editing.value.type === 'sqlite') {
    editing.value.host = ''
    editing.value.database = ''
    editing.value.user = ''
  }
}
const deleting = ref<Entity>(),
  deleteError = ref('')
function confirmDelete(row: Entity) {
  deleting.value = row
  deleteError.value = ''
}
async function erase() {
  if (!deleting.value) return
  deleteError.value = ''
  try {
    await remove('sources', deleting.value.id)
    if (current.value?.id === deleting.value.id) closeConnection()
    deleting.value = undefined
    await load()
  } catch (e) {
    deleteError.value = (e as Error).message
  }
}
const filtered = computed(() =>
  sources.value.filter((s) => [s.name, s.host, s.database, s.filePath].join(' ').includes(search.value)),
)
const filteredTables = computed(() =>
  tables.value.filter((t) =>
    [t.schema, t.name, t.comment].join(' ').toLowerCase().includes(tableSearch.value.toLowerCase()),
  ),
)
const running = computed(() => snapshots.value.some((s) => s.status === 'RUNNING'))
const labels: Record<string, string> = {
  RUNNING: '正在采集',
  SUCCESS: '采集完成',
  FAILED: '采集失败',
  CANCELLED: '已取消',
  INTERRUPTED: '已中断',
}
let timer: ReturnType<typeof setInterval>
async function load() {
  try {
    sources.value = (await list('sources')).list
    if (canWrite.value) {
      const [runs, drivers] = await Promise.all([
        request('/api/ingestion/snapshots'),
        request('/api/ingestion/connectors'),
      ])
      snapshots.value = runs.list
      connectors.value = drivers.list
    }
  } catch (e) {
    error.value = (e as Error).message
  }
}
onMounted(() => {
  load()
  timer = setInterval(() => {
    if (running.value) load()
  }, 1500)
})
onUnmounted(() => {
  clearInterval(timer)
  password.value = ''
})
function edit(row?: Entity) {
  editing.value = {
    name: '',
    type: 'postgresql',
    host: '',
    port: 5432,
    database: '',
    user: '',
    sslmode: 'prefer',
    description: '',
    filePath: '',
    serviceMode: 'service',
    authDatabase: 'admin',
    caFile: '',
    consistencyMode: 'strict',
    ...row,
  }
  formError.value = ''
  opened.value = true
}
async function submit() {
  saving.value = true
  formError.value = ''
  try {
    await save('sources', editing.value)
    if (current.value?.id === editing.value.id) closeConnection()
    opened.value = false
    await load()
    notify('数据源配置已保存，密码未保存')
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}
function choose(row: Entity) {
  current.value = row
  password.value = ''
  tables.value = []
  selected.value = []
  info.value = undefined
  actionError.value = ''
  tableSearch.value = ''
  snapshotName.value = row.name + '-原始库'
}
function closeConnection() {
  current.value = undefined
  password.value = ''
}
async function remote(action: 'test' | 'tables') {
  if (!current.value) return
  busy.value = true
  actionError.value = ''
  try {
    const r = await request('/api/ingestion/sources/' + current.value.id + '/' + action, 'POST', {
      password: password.value,
    })
    if (action === 'tables') {
      tables.value = r.list
      selected.value = r.list.map((t: Entity) => t.oid)
    } else {
      info.value = r
      platform.health = await request('/api/health')
      await load()
    }
  } catch (e) {
    actionError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
function selectVisible() {
  selected.value = [...new Set([...selected.value, ...filteredTables.value.map((t) => t.oid)])]
}
async function capture(all = false) {
  if (!current.value) return
  busy.value = true
  actionError.value = ''
  try {
    await request('/api/ingestion/sources/' + current.value.id + '/snapshots', 'POST', {
      password: password.value,
      name: snapshotName.value,
      tables: all ? null : selected.value,
    })
    password.value = ''
    await load()
    notify('采集已开始，完成后可在本地原始库查看')
  } catch (e) {
    actionError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
async function cancel(s: Entity) {
  try {
    await request('/api/ingestion/snapshots/' + s.id + '/cancel', 'POST', {})
    await load()
  } catch (e) {
    error.value = (e as Error).message
  }
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>数据库接入</h1>
      <p>批量读取常见数据库的业务表或文档，生成本地原始库，后续治理使用本地副本。</p>
    </div>
    <button class="primary" :disabled="!canWrite || !connectors.length" @click="edit()">
      新增数据源
    </button>
  </div>
  <div class="info-banner">
    只读采集 → 本地原始库 → 治理数据集 →
    拖拽治理与质量报告。采集不回写远程数据库，密码仅用于当次操作。<RouterLink to="/access/raw"
      >查看本地原始库 →</RouterLink
    >
  </div>
  <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
  <section class="panel">
    <div class="table-toolbar">
      <input v-model="search" aria-label="搜索数据源" placeholder="搜索名称、主机或数据库" /><span
        >共{{ filtered.length }}条</span
      ><button @click="load">刷新</button>
    </div>
    <DataTable
      class="source-table"
      :rows="filtered"
      :columns="[
        { key: 'name', label: '名称' },
        { key: 'type', label: '类型' },
        { key: 'host', label: '主机' },
        { key: 'database', label: '数据库' },
      ]"
      ><template #actions="{ row }"
        ><button class="text-button" :disabled="!canWrite" @click="edit(row)">编辑</button
        ><button
          class="text-button"
          :disabled="!canWrite || !spec(row.type).available"
          @click="choose(row)"
        >
          连接与采集</button
        ><button
          class="text-button"
          :disabled="!canWrite || snapshots.some((s) => s.sourceId === row.id)"
          title="已有采集记录的数据源保留用于追溯"
          @click="confirmDelete(row)"
        >
          删除
        </button></template
      ><template #type="{ row }">{{ spec(row.type).label }}</template
      ><template #host="{ row }">{{ row.type === 'sqlite' ? '本机文件' : row.host }}</template
      ><template #database="{ row }"
        ><span class="source-database" :title="row.type === 'sqlite' ? row.filePath : row.database"
          >{{ row.type === 'sqlite' ? row.filePath : row.database }}</span
        ></template></DataTable
    >
    <p v-if="!canWrite" class="muted">数据库采集及原始库中的训练数据仅管理员可访问。</p>
    <p class="muted tiny">
      支持PostgreSQL、MySQL、MariaDB、SQL
      Server、Oracle、SQLite、MongoDB和ClickHouse。按类型展示真实连接参数与一致性限制。
    </p>
  </section>
  <section v-if="current" class="panel raw-connection">
    <div class="local-section-head">
      <h2>{{ current.name }} · 只读连接</h2>
      <button @click="closeConnection">关闭采集配置</button>
    </div>
    <p class="muted">
      {{
        current.type === 'sqlite'
          ? current.filePath
          : current.host +
            ':' +
            current.port +
            ' / ' +
            current.database +
            ' / ' +
            (current.user || '默认账号')
      }}
    </p>
    <form @submit.prevent="remote('test')">
      <div class="form-grid">
        <label v-if="current.type !== 'sqlite'"
          >{{ passwordRequired ? '本次数据库密码' : '本次数据库密码（可留空）'
          }}<input
            v-model="password"
            type="password"
            autocomplete="off"
            :required="passwordRequired"
            maxlength="1024"
            :disabled="busy" /></label
        ><label
          >本次原始库名称<input v-model="snapshotName" maxlength="120" :disabled="busy"
        /></label>
      </div>
      <div class="raw-actions">
        <button type="submit" :disabled="busy || (passwordRequired && !password)">
          测试只读连接</button
        ><button
          type="button"
          :disabled="busy || (passwordRequired && !password)"
          @click="remote('tables')"
        >
          扫描业务表</button
        ><button
          type="button"
          class="primary"
          :disabled="busy || (passwordRequired && !password) || running"
          @click="capture(true)"
        >
          采集全部业务表
        </button>
      </div>
    </form>
    <p v-if="busy" role="status">正在处理，请稍候…</p>
    <p v-if="actionError" class="error-banner" role="alert">{{ actionError }}</p>
    <p v-if="info" class="success-banner" role="status">
      连接成功 · {{ currentSpec.label }} {{ info.version }} · 只读采集{{
        info.read_only === 'on' ? '已开启' : '未开启'
      }}
      · {{ info.consistent_snapshot === false ? '尽力读取（无整批一致性）' : '一致快照' }}
    </p>
    <template v-if="tables.length"
      ><div class="table-toolbar">
        <input v-model="tableSearch" aria-label="筛选远程表" placeholder="按表名或说明筛选" /><span
          >已选{{ selected.length }} / {{ tables.length }}张表</span
        ><button @click="selectVisible">全选当前筛选</button
        ><button @click="selected = []">清空选择</button>
      </div>
      <div class="raw-table-picker table-wrap">
        <table>
          <thead>
            <tr>
              <th>选择</th>
              <th>模式 / 表名</th>
              <th>估算行数</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in filteredTables" :key="t.oid">
              <td>
                <input
                  v-model="selected"
                  :value="t.oid"
                  type="checkbox"
                  :aria-label="'选择 ' + t.schema + '.' + t.name"
                />
              </td>
              <td class="mono">{{ t.schema }}.{{ t.name }}</td>
              <td>{{ t.estimated_rows }}</td>
              <td>{{ t.comment || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="muted tiny">
        估算行数来自数据库统计，完成后显示实际采集行数。仅采集当前账号可访问的业务对象；{{
          currentSpec.note
        }}
      </p>
      <button
        class="primary"
        :disabled="busy || (passwordRequired && !password) || !selected.length || running"
        @click="capture()"
      >
        采集所选{{ selected.length }}张表
      </button></template
    >
  </section>
  <section class="panel">
    <div class="local-section-head">
      <h2>采集记录与进度</h2>
      <RouterLink to="/access/raw">进入本地原始库 →</RouterLink>
    </div>
    <div v-if="!snapshots.length" class="empty">还没有采集记录</div>
    <article v-for="s in snapshots" :key="s.id" class="raw-progress">
      <div class="local-section-head">
        <strong>{{ s.name }}</strong
        ><span :class="['badge', s.status]">{{ labels[s.status] }}</span>
      </div>
      <p>
        {{ s.completedTables }} / {{ s.tableCount || '待扫描' }} 张表 · {{ s.rowCount }} 行 ·
        {{ dateText(s.createdAt) }}
      </p>
      <p v-if="s.currentTable" class="mono">
        正在读取 {{ s.currentTable }} · {{ s.currentTableRows || 0 }} 行
      </p>
      <p v-if="s.error" class="error-banner">{{ s.error }}</p>
      <progress
        v-if="s.status === 'RUNNING'"
        :value="s.completedTables"
        :max="s.tableCount || 1"
        aria-label="采集进度"
      />
      <div class="raw-actions">
        <button v-if="s.status === 'RUNNING'" :disabled="s.cancelRequested" @click="cancel(s)">
          {{ s.cancelRequested ? '正在取消…' : '取消采集' }}</button
        ><RouterLink
          v-if="s.status === 'SUCCESS'"
          :to="'/access/raw?snapshot=' + s.id"
          class="button"
          >查看本地原始库</RouterLink
        >
      </div>
    </article>
  </section>
  <Modal :open="Boolean(deleting)" title="删除未使用的数据源" @close="deleting = undefined"
    ><p>确认删除“{{ deleting?.name }}”？已有采集记录的数据源受引用保护。</p>
    <p v-if="deleteError" class="error-banner" role="alert">{{ deleteError }}</p>
    <div class="modal-actions">
      <button @click="deleting = undefined">取消</button><button @click="erase">确认删除</button>
    </div></Modal
  >
  <Modal :open="opened" :title="editing.id ? '编辑数据源' : '新增数据源'" @close="opened = false"
    ><form @submit.prevent="submit">
      <p v-if="formError" class="error-banner" role="alert">{{ formError }}</p>
      <div class="form-grid">
        <label>名称<input v-model="editing.name" required maxlength="120" /></label
        ><label
          >数据库类型<select v-model="editing.type" @change="typeChanged">
            <option v-for="c in connectors" :key="c.type" :value="c.type" :disabled="!c.available">
              {{ c.label }}{{ c.available ? '' : '（需安装驱动）' }}
            </option>
          </select></label
        ><label v-if="editing.type !== 'sqlite'"
          >主机地址<input
            v-model="editing.host"
            required
            placeholder="IP或域名，不带http://" /></label
        ><label v-if="editing.type !== 'sqlite'"
          >端口<input
            v-model.number="editing.port"
            type="number"
            min="1"
            max="65535"
            required /></label
        ><label v-if="editing.type === 'sqlite'"
          >SQLite文件绝对路径<input
            v-model="editing.filePath"
            required
            placeholder="例如 E:/data/business.sqlite3"
        /></label>
        <label v-else
          >{{ editing.type === 'oracle' ? 'Service Name / SID' : '数据库名称'
          }}<input v-model="editing.database" required maxlength="120"
        /></label>
        <label v-if="editing.type === 'oracle'"
          >Oracle连接标识<select v-model="editing.serviceMode">
            <option value="service">Service Name</option>
            <option value="sid">SID</option>
          </select></label
        >
        <label v-if="editing.type !== 'sqlite'"
          >数据库账号<input
            v-model="editing.user"
            :required="!['mongodb', 'clickhouse'].includes(editing.type)"
            maxlength="120"
        /></label>
        <label v-if="editing.type === 'mongodb'"
          >认证数据库<input v-model="editing.authDatabase" placeholder="admin"
        /></label>
        <label v-if="editing.type !== 'sqlite'"
          >传输加密<select v-model="editing.sslmode">
            <option value="prefer">连接器默认方式</option>
            <option value="require">必须加密</option>
          </select></label
        ><label v-if="editing.type !== 'sqlite'"
          >CA证书文件（可选）<input v-model="editing.caFile" placeholder="后端本机CA证书绝对路径"
        /></label>
        <label
          >快照一致性<select v-model="editing.consistencyMode">
            <option value="strict">严格一致快照</option>
            <option value="best_effort">尽力读取（期间可能变化）</option>
          </select></label
        >
        <label>说明<input v-model="editing.description" /></label>
      </div>
      <p class="info-banner">{{ spec(editing.type).note }}</p>
      <p v-if="editing.consistencyMode === 'best_effort'" class="info-banner">
        尽力读取不保证整库同一时点；采集期间原数据可能变化，快照会记录此限制。
      </p>
      <p class="muted tiny">
        保存参数不保存密码。TLS默认方式按连接器配置；必须加密会启用TLS/TCPS/HTTPS，私有证书可提供CA文件。SQLite路径为后端本机已有文件；保存参数不会连接。
      </p>
      <div class="modal-actions">
        <button type="button" @click="opened = false">取消</button
        ><button class="primary" :disabled="saving">保存数据源</button>
      </div>
    </form></Modal
  >
</template>
<style scoped>
.source-table :deep(table) {
  min-width: 720px;
}
.source-database {
  display: block;
  max-width: 240px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
</style>
