<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request } from '../api/client'
import type { Entity } from '../api/client'
import { act, dateText, notify, platform } from '../stores/platform'
import DataTable from '../components/DataTable.vue'
import Modal from '../components/Modal.vue'
import Icon from '../components/Icon.vue'
const rows = ref<Entity[]>([]),
  opened = ref(false),
  form = ref({ name: '', password: '', role: 'reader' }),
  formError = ref(''),
  saving = ref(false)
async function load() {
  rows.value = await request('/api/auth/users')
}
onMounted(() => {
  if (platform.user?.role === 'admin') act(load)
})
async function submit() {
  formError.value = ''
  saving.value = true
  try {
    await request('/api/auth/users', 'POST', form.value)
    opened.value = false
    form.value = { name: '', password: '', role: 'reader' }
    await load()
    notify('账号已创建')
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '账号创建失败'
  } finally {
    saving.value = false
  }
}
function openForm() {
  formError.value = ''
  form.value = { name: '', password: '', role: 'reader' }
  opened.value = true
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>账号管理</h1>
      <p>管理员可以修改配置和执行任务，只读账号可以查看配置与结果。</p>
    </div>
    <button v-if="platform.user?.role === 'admin'" class="primary" @click="openForm">
      <Icon name="plus" />新增账号
    </button>
  </div>
  <section class="panel">
    <div v-if="platform.user?.role !== 'admin'" class="empty">此页面需要管理员权限。</div>
    <DataTable
      v-else
      :rows="rows"
      :columns="[
        { key: 'name', label: '账号' },
        { key: 'role', label: '角色' },
        { key: 'createdAt', label: '创建时间' },
      ]"
      ><template #role="{ row }"
        ><span class="badge">{{ row.role === 'admin' ? '管理员' : '只读用户' }}</span></template
      ><template #createdAt="{ row }">{{ dateText(row.createdAt) }}</template></DataTable
    >
  </section>
  <div class="info-banner">
    默认本机自动登录便于开发。关闭自动登录前，请先创建一个已知密码的管理员账号。当前服务仅监听本机。
  </div>
  <Modal :open="opened" title="新增账号" @close="opened = false"
    ><form @submit.prevent="submit">
      <p v-if="formError" class="error-banner" role="alert">{{ formError }}</p>
      <label>账号<input v-model="form.name" required maxlength="80" autocomplete="off" /></label
      ><label
        >密码<input
          v-model="form.password"
          type="password"
          required
          minlength="10"
          maxlength="200"
          autocomplete="new-password" /></label
      ><label
        >角色<select v-model="form.role">
          <option value="reader">只读用户</option>
          <option value="admin">管理员</option>
        </select></label
      >
      <div class="modal-actions">
        <button type="button" @click="opened = false">取消</button
        ><button class="primary" type="submit" :disabled="saving">
          {{ saving ? '创建中…' : '创建账号' }}
        </button>
      </div>
    </form></Modal
  >
</template>
