<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { Entity } from '../api/client'
import { platform, dateText } from '../stores/platform'
import { local, statusLabels } from '../local/shared'
import DataTable from '../components/DataTable.vue'
import Modal from '../components/Modal.vue'
const route = useRoute(),
  grantMode = ['/service/applications', '/service/authorized'].includes(route.path),
  authorized = route.path === '/service/authorized'
const kind = grantMode ? 'grants' : 'approvals'
const scopes: Record<string, string[]> = {
  '/standard/approval': ['elements', 'dictionaries', 'qualifiers', 'businessTypes'],
  '/asset/approval': ['assets'],
  '/service/approval': ['services'],
  '/service/view-audit': ['views'],
}
const typeLabels: Record<string, string> = {
  elements: '数据元',
  dictionaries: '代码集',
  qualifiers: '限定词',
  businessTypes: '业务分类',
  assets: '数据资源',
  services: '数据服务',
  views: '本地视图',
}
const allowed = scopes[route.path] || []
const boot = ref<Entity>({ targets: {}, apps: [], services: [] }),
  rows = ref<Entity[]>([]),
  status = ref(authorized ? 'approved' : ''),
  search = ref(''),
  opened = ref(false),
  form = ref<Entity>({}),
  error = ref(''),
  formError = ref(''),
  saving = ref(false),
  decision = ref<Entity>(),
  note = ref(''),
  decisionError = ref(''),
  detail = ref<Entity>(),
  page = ref(1)
const canReview = computed(() => platform.user?.role === 'admin')
const targets = computed<Entity[]>(() => boot.value.targets[form.value.targetKind] || [])
const filtered = computed(() =>
  rows.value.filter(
    (r) =>
      (grantMode || allowed.includes(r.targetKind)) &&
      (!status.value || r.status === status.value) &&
      r.name.includes(search.value),
  ),
)
async function load() {
  try {
    const [data, list] = await Promise.all([local('bootstrap'), local('records/' + kind)])
    boot.value = data
    rows.value = list.list
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  }
}
onMounted(load)
function targetChanged() {
  form.value.targetId = targets.value[0]?.id || ''
}
function open() {
  formError.value = ''
  form.value = {
    targetKind: allowed[0],
    targetId: '',
    appId: boot.value.apps[0]?.id || '',
    serviceId: boot.value.services.find((s: Entity) => s.published)?.id || '',
    reason: '',
  }
  targetChanged()
  opened.value = true
}
async function submit() {
  saving.value = true
  formError.value = ''
  try {
    await local(kind, 'POST', form.value)
    opened.value = false
    await load()
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '提交失败'
  } finally {
    saving.value = false
  }
}
function review(row: Entity, action: string) {
  decision.value = { ...row, action }
  note.value = ''
  decisionError.value = ''
}
async function decide() {
  if (!decision.value) return
  saving.value = true
  decisionError.value = ''
  try {
    await local('action/' + kind + '/' + decision.value.id + '/' + decision.value.action, 'POST', {
      note: note.value,
    })
    decision.value = undefined
    await load()
  } catch (e) {
    decisionError.value = e instanceof Error ? e.message : '处理失败'
  } finally {
    saving.value = false
  }
}
async function show(row: Entity) {
  detail.value = await local('records/' + kind + '/' + row.id)
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>{{ route.meta.title }}</h1>
      <p>
        {{
          grantMode
            ? '按应用与服务进行申请、审核和撤销；未获授权或已停用的应用不能查询服务。'
            : '本地管理员单级审核，保留提交版本；对象变更后需要重新提交。'
        }}
      </p>
    </div>
    <button v-if="!authorized" class="primary" @click="open">
      {{ grantMode ? '申请服务授权' : '提交审核申请' }}
    </button>
  </div>
  <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
  <section class="panel">
    <div class="table-toolbar">
      <input
        v-model="search"
        aria-label="搜索审核记录"
        placeholder="搜索名称"
        @input="page = 1"
      /><select v-model="status" aria-label="审核状态" @change="page = 1">
        <option value="">全部状态</option>
        <option v-if="!authorized" value="pending">待处理</option>
        <option value="approved">已通过</option>
        <option v-if="!authorized" value="rejected">已驳回</option>
        <option :value="grantMode ? 'revoked' : 'withdrawn'">
          {{ grantMode ? '已撤销' : '已撤回' }}
        </option></select
      ><button @click="load">刷新</button>
    </div>
    <DataTable
      :rows="filtered.slice((page - 1) * 10, page * 10)"
      :columns="[
        { key: 'name', label: '申请对象' },
        { key: 'status', label: '状态' },
        { key: 'submittedBy', label: '申请人' },
        { key: 'createdAt', label: '提交时间' },
      ]"
      ><template #status="{ row }"
        ><span class="badge">{{ statusLabels[row.status] }}</span></template
      ><template #createdAt="{ row }">{{ dateText(row.createdAt) }}</template
      ><template #actions="{ row }"
        ><button class="text-button" @click="show(row)">查看详情</button
        ><template v-if="row.status === 'pending'"
          ><button v-if="canReview" class="text-button" @click="review(row, 'approve')">
            通过审核</button
          ><button v-if="canReview" class="text-button red" @click="review(row, 'reject')">
            驳回申请</button
          ><button
            v-if="!grantMode && (canReview || row.submittedUserId === platform.user?.id)"
            class="text-button"
            @click="review(row, 'withdraw')"
          >
            撤回申请
          </button></template
        ><button
          v-if="grantMode && row.status === 'approved' && canReview"
          class="text-button red"
          @click="review(row, 'revoke')"
        >
          撤销授权
        </button></template
      ></DataTable
    >
    <div class="pagination">
      <span>共{{ filtered.length }}条 · 第{{ page }}页</span
      ><button :disabled="page <= 1" @click="page--">上一页</button
      ><button :disabled="page * 10 >= filtered.length" @click="page++">下一页</button>
    </div>
  </section>
  <Modal :open="opened" :title="grantMode ? '申请服务授权' : '提交审核申请'" @close="opened = false"
    ><form @submit.prevent="submit">
      <p v-if="formError" class="error-banner" role="alert">{{ formError }}</p>
      <template v-if="grantMode"
        ><label
          >应用<select v-model="form.appId" required>
            <option v-for="a in boot.apps" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select></label
        ><label
          >已发布服务<select v-model="form.serviceId" required>
            <option
              v-for="s in boot.services.filter((x: Entity) => x.published)"
              :key="s.id"
              :value="s.id"
            >
              {{ s.name }}
            </option>
          </select></label
        ></template
      ><template v-else
        ><label
          >对象类型<select v-model="form.targetKind" @change="targetChanged">
            <option v-for="k in allowed" :key="k" :value="k">{{ typeLabels[k] }}</option>
          </select></label
        ><label
          >审核对象<select v-model="form.targetId" required>
            <option v-for="t in targets" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select></label
        ></template
      ><label>申请说明<textarea v-model="form.reason" maxlength="2000" rows="4" /></label>
      <div class="modal-actions">
        <button type="button" @click="opened = false">取消</button
        ><button class="primary" type="submit" :disabled="saving">提交申请</button>
      </div>
    </form></Modal
  >
  <Modal :open="!!decision" title="处理申请" @close="decision = undefined"
    ><form @submit.prevent="decide">
      <p>{{ decision?.name }}</p>
      <p v-if="decisionError" class="error-banner" role="alert">{{ decisionError }}</p>
      <label>处理意见<textarea v-model="note" maxlength="2000" rows="4" /></label>
      <div class="modal-actions">
        <button type="button" @click="decision = undefined">取消</button
        ><button class="primary" type="submit" :disabled="saving">确认处理</button>
      </div>
    </form></Modal
  >
  <Modal :open="!!detail" title="申请详情" wide @close="detail = undefined"
    ><p>{{ detail?.name }} · {{ statusLabels[detail?.status] }}</p>
    <p>申请说明：{{ detail?.reason || '无' }}</p>
    <p>处理意见：{{ detail?.reviewNote || detail?.note || '尚未填写' }}</p>
    <pre class="local-json">{{ JSON.stringify(detail, null, 2) }}</pre>
    <div class="modal-actions"><button @click="detail = undefined">关闭详情</button></div></Modal
  >
</template>
