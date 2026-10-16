<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { request } from '../api/client'
import type { Entity, Page } from '../api/client'
import { act, dateText, notify, platform, refresh } from '../stores/platform'
import DataTable from '../components/DataTable.vue'
import Modal from '../components/Modal.vue'
import Icon from '../components/Icon.vue'
const rows = ref<Entity[]>([]),
  status = ref(''),
  selected = ref<Entity>(),
  note = ref(''),
  dialogError = ref(''),
  resolving = ref(false)
const filtered = computed(() =>
  rows.value.filter((r) => !status.value || r.status === status.value),
)
async function load() {
  rows.value = (await request<Page>('alerts?pageSize=500')).list
  await refresh()
}
onMounted(() => act(load))
async function resolve() {
  if (resolving.value || !selected.value) return
  dialogError.value = ''
  resolving.value = true
  try {
    await request('alerts/' + selected.value!.id + '/resolve', 'POST', { note: note.value })
    selected.value = undefined
    note.value = ''
    await load()
    notify('预警已标记处理')
  } catch (e) {
    dialogError.value = e instanceof Error ? e.message : '处理失败'
  } finally {
    resolving.value = false
  }
}
function openAlert(alert: Entity) {
  note.value = ''
  dialogError.value = ''
  selected.value = alert
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>数据预警</h1>
      <p>质量检测产生的真实问题记录，关联对应运行报告。</p>
    </div>
    <button @click="act(load)"><Icon name="refresh" />刷新</button>
  </div>
  <section class="panel">
    <div class="table-toolbar">
      <select v-model="status" aria-label="预警状态">
        <option value="">全部状态</option>
        <option value="open">待处理</option>
        <option value="resolved">已处理</option></select
      ><span class="muted">共 {{ filtered.length }} 条</span>
    </div>
    <DataTable
      :rows="filtered"
      :columns="[
        { key: 'name', label: '问题规则' },
        { key: 'field', label: '检查字段' },
        { key: 'failed', label: '问题记录数' },
        { key: 'status', label: '状态' },
        { key: 'createdAt', label: '生成时间' },
      ]"
      empty="暂无预警，执行质量检测后会自动生成"
      ><template #status="{ row }"
        ><span :class="['badge', row.status === 'open' ? 'FAILED' : 'SUCCESS']">{{
          row.status === 'open' ? '待处理' : '已处理'
        }}</span></template
      ><template #createdAt="{ row }">{{ dateText(row.createdAt) }}</template
      ><template #actions="{ row }"
        ><RouterLink :to="'/develop/runs?run=' + row.runId">运行报告</RouterLink
        ><button class="text-button" @click="openAlert(row)">
          {{ row.status === 'open' ? '查看与处理' : '查看详情' }}
        </button></template
      ></DataTable
    >
  </section>
  <Modal :open="!!selected" title="预警详情" @close="selected = undefined"
    ><template v-if="selected"
      ><p v-if="dialogError" class="error-banner" role="alert">{{ dialogError }}</p>
      <h3>{{ selected.name }}</h3>
      <p>字段 {{ selected.field }} · {{ selected.failed }} 条问题记录</p>
      <p class="muted">
        节点输入中的问题索引（从0开始，最多100个）：{{ selected.failedIndexes.join(', ') }}
      </p>
      <p v-if="selected.status === 'resolved'">
        处理人：{{ selected.resolvedBy }}<br />处理说明：{{ selected.note || '未填写' }}
      </p>
      <template v-else-if="platform.user?.role === 'admin'"
        ><label
          >处理说明<textarea
            v-model="note"
            rows="4"
            placeholder="记录核查或整改情况；标记处理不会自动修复源数据。"
          />
        </label>
        <div class="modal-actions">
          <button @click="selected = undefined">取消</button
          ><button class="primary" :disabled="resolving" @click="resolve">
            {{ resolving ? '处理中…' : '标记已处理' }}
          </button>
        </div></template
      ></template
    ></Modal
  >
</template>
