<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { local, downloadJson } from '../local/shared'
import type { Entity } from '../api/client'
import LocalResult from '../components/LocalResult.vue'
const services = ref<Entity[]>([]),
  selected = ref(''),
  contract = ref<Entity>(),
  error = ref(''),
  credential = ref(''),
  credentialType = ref('X-App-Key'),
  queryResult = ref<Entity>(),
  querying = ref(false)
async function query() {
  error.value = ''
  querying.value = true
  queryResult.value = undefined
  try {
    const response = await fetch('/api/published/' + selected.value + '/query?pageSize=20', {
      headers: { [credentialType.value]: credential.value },
      credentials: 'omit',
    })
    const value = await response.json()
    if (!response.ok || !value.success) throw new Error(value.message || '查询失败')
    queryResult.value = {
      name: '服务查询结果',
      metrics: { rowCount: value.data.total },
      rows: value.data.list,
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '查询失败'
  } finally {
    querying.value = false
  }
}
async function load() {
  try {
    services.value = (await local('bootstrap')).services
    selected.value ||= services.value[0]?.id || ''
    await choose()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  }
}
async function choose() {
  if (!selected.value) return
  try {
    contract.value = await local('contracts/' + selected.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  }
}
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>服务规约</h1>
      <p>按实际服务生成字段白名单、访问凭据、分页、限流和错误响应说明。</p>
    </div>
    <button @click="load">刷新</button>
  </div>
  <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
  <section class="panel">
    <label
      >数据服务<select v-model="selected" @change="choose">
        <option v-for="s in services" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select></label
    ><template v-if="contract"
      ><div class="local-section-head">
        <h2>{{ contract.info.title }}</h2>
        <button @click="downloadJson(contract, contract.info.title + '-OpenAPI')">
          下载OpenAPI规约
        </button>
      </div>
      <p v-if="!contract['x-published']" class="info-banner">
        此服务尚未发布，发布后可按规约调用。
      </p>
      <p>GET /api/published/{{ selected }}/query</p>
      <p>分页：pageNum从1开始，pageSize最多500；每分钟最多60次查询。</p>
      <p>认证：X-API-Key服务密钥，或已启用且获得服务授权的应用X-App-Key凭据。</p>
      <div class="field-chips">
        <span v-for="f in contract['x-fields']" :key="f">{{ f }}</span>
      </div>
      <form @submit.prevent="query">
        <div class="form-grid">
          <label
            >凭据类型<select v-model="credentialType">
              <option value="X-App-Key">应用凭据 X-App-Key</option>
              <option value="X-API-Key">服务密钥 X-API-Key</option>
            </select></label
          ><label
            >访问凭据<input v-model="credential" type="password" autocomplete="off" required
          /></label>
        </div>
        <div class="modal-actions">
          <button class="primary" type="submit" :disabled="querying">
            {{ querying ? '查询中…' : '执行服务查询' }}
          </button>
        </div>
      </form>
      <pre class="local-json">{{ JSON.stringify(contract, null, 2) }}</pre>
    </template>
    <p v-else class="muted">请先登记数据服务。</p>
  </section>
  <LocalResult :value="queryResult" />
</template>
