<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { local, statusLabels, downloadJson } from '../local/shared'
import { dateText, platform } from '../stores/platform'
import type { Entity } from '../api/client'
import LocalRecordsView from './LocalRecordsView.vue'
import DataTable from '../components/DataTable.vue'
import Modal from '../components/Modal.vue'
const tab = ref('deliveries'),
  rows = ref<Entity[]>([]),
  channels = ref<Entity[]>([]),
  detail = ref<Entity>(),
  selectedEvent = ref<Entity>(),
  channelId = ref(''),
  error = ref(''),
  busy = ref(false),
  page = ref(1)
const labels: Record<string, string> = {
  deliveries: '投递队列',
  events: '变化事件',
  inbox: '本地收件箱',
  channels: '收件通道',
}
const columns = computed(() => [
  { key: 'name', label: '名称' },
  ...(tab.value === 'inbox'
    ? [{ key: 'recipient', label: '收件人' }]
    : tab.value === 'events'
      ? [
          { key: 'changeType', label: '变化类型' },
          { key: 'count', label: '变化数量' },
        ]
      : [
          { key: 'status', label: '状态' },
          { key: 'attempts', label: '尝试次数' },
          { key: 'error', label: '最近错误' },
        ]),
  { key: 'createdAt', label: '创建时间' },
])
async function load() {
  if (tab.value === 'channels') return
  try {
    error.value = ''
    const [values, boot] = await Promise.all([local('records/' + tab.value), local('bootstrap')])
    rows.value = values.list
    channels.value = boot.channels
    channelId.value ||= boot.channels[0]?.id || ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  }
}
onMounted(load)
async function choose(value: string) {
  tab.value = value
  page.value = 1
  await load()
}
async function show(row: Entity) {
  try {
    detail.value = await local('records/' + tab.value + '/' + row.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  }
}
async function deliver(row: Entity) {
  busy.value = true
  try {
    await local('action/deliveries/' + row.id + '/deliver', 'POST', {})
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '投递失败'
  } finally {
    busy.value = false
  }
}
async function enqueue() {
  if (!selectedEvent.value) return
  busy.value = true
  try {
    await local('action/events/' + selectedEvent.value.id + '/enqueue', 'POST', {
      channelId: channelId.value,
    })
    selectedEvent.value = undefined
    await choose('deliveries')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加入队列失败'
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>数据推送</h1>
      <p>将本地变化事件排入队列并实际投递到SQLite收件箱，保留成功、失败和重试记录。</p>
    </div>
    <button @click="load">刷新</button>
  </div>
  <p v-if="platform.user?.role !== 'admin'" class="info-banner">此功能需要管理员权限。</p>
  <template v-else
    ><div class="local-tabs">
      <button
        v-for="(label, key) in labels"
        :key="key"
        :class="{ primary: tab === key }"
        @click="choose(String(key))"
      >
        {{ label }}
      </button>
    </div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <LocalRecordsView v-if="tab === 'channels'" kind="channels" embedded />
    <section v-else class="panel">
      <p class="muted">
        {{
          tab === 'events'
            ? '在比对订阅中执行比对后，会生成真实的增删改事件。'
            : tab === 'inbox'
              ? '成功投递的消息保存在本地收件箱，不会向外部系统发送。'
              : '已启用的通道会在平台运行期间自动投递；失败记录可修复通道后手动重试。'
        }}
      </p>
      <DataTable :rows="rows.slice((page - 1) * 20, page * 20)" :columns="columns"
        ><template #status="{ row }"
          ><span class="badge">{{ statusLabels[row.status] }}</span></template
        ><template #changeType="{ row }">{{ statusLabels[row.changeType] }}</template
        ><template #createdAt="{ row }">{{ dateText(row.createdAt) }}</template
        ><template #actions="{ row }"
          ><button class="text-button" @click="show(row)">查看详情</button
          ><button
            v-if="tab === 'deliveries' && row.status !== 'delivered'"
            class="text-button"
            :disabled="busy"
            @click="deliver(row)"
          >
            {{ row.status === 'failed' ? '重试投递' : '立即投递' }}</button
          ><button v-if="tab === 'events'" class="text-button" @click="selectedEvent = row">
            加入投递队列
          </button></template
        ></DataTable
      >
      <div class="pagination">
        <span>共{{ rows.length }}条 · 第{{ page }}页</span
        ><button :disabled="page <= 1" @click="page--">上一页</button
        ><button :disabled="page * 20 >= rows.length" @click="page++">下一页</button>
      </div>
    </section></template
  >
  <Modal :open="!!detail" title="消息详情" wide @close="detail = undefined">
    <pre class="local-json">{{ JSON.stringify(detail, null, 2) }}</pre>
    <div class="modal-actions">
      <button @click="downloadJson(detail, detail?.name || '本地消息')">下载消息</button
      ><button @click="detail = undefined">关闭详情</button>
    </div></Modal
  >
  <Modal :open="!!selectedEvent" title="选择收件通道" @close="selectedEvent = undefined"
    ><form @submit.prevent="enqueue">
      <p>{{ selectedEvent?.name }}</p>
      <label
        >收件通道<select v-model="channelId" required>
          <option v-for="c in channels" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select></label
      >
      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
      <div class="modal-actions">
        <button type="button" @click="selectedEvent = undefined">取消</button
        ><button class="primary" type="submit" :disabled="busy">确认加入队列</button>
      </div>
    </form></Modal
  >
</template>
