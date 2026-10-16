<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { groups, pages } from './router/pages'
import type { PageDefinition } from './router/pages'
import { act, boot, notify, platform, refresh } from './stores/platform'
import { connectionState, request } from './api/client'
import Icon from './components/Icon.vue'
import { version as pageVersion } from '../package.json'
const route = useRoute(),
  router = useRouter(),
  loginError = ref(''),
  loginName = ref('admin'),
  password = ref('')
const initializing = ref(true)
const updateAvailable = computed(() =>
  Boolean(platform.health.version && platform.health.version !== pageVersion),
)
let versionTimer: ReturnType<typeof setInterval>
async function checkVersion() {
  if (document.visibilityState !== 'visible') return
  try {
    platform.health = await request('/api/health')
  } catch {
    // A temporarily unavailable service does not mean the page needs reloading.
  }
}
function reloadPage() {
  window.location.reload()
}
const current = computed(() => route.meta.page as PageDefinition | undefined)
const sidePages = computed(() =>
  pages.filter((p) => p.group === current.value?.group && p.group !== 'home'),
)
const sections = computed(() => [...new Set(sidePages.value.map((p) => p.section))])
onMounted(async () => {
  window.addEventListener('focus', checkVersion)
  document.addEventListener('visibilitychange', checkVersion)
  versionTimer = setInterval(checkVersion, 60000)
  try {
    await boot()
  } catch (e) {
    loginError.value = e instanceof Error ? e.message : '连接失败'
  } finally {
    initializing.value = false
  }
})
onUnmounted(() => {
  clearInterval(versionTimer)
  window.removeEventListener('focus', checkVersion)
  document.removeEventListener('visibilitychange', checkVersion)
})
async function login() {
  await act(async () => {
    platform.user = await request('/api/auth/login', 'POST', {
      name: loginName.value,
      password: password.value,
    })
    password.value = ''
    await refresh()
    platform.ready = true
  })
}
async function logout() {
  await act(async () => {
    await request('/api/auth/logout', 'POST', {})
    platform.user = null
    platform.ready = false
  })
}
</script>
<template>
  <div v-if="!platform.ready" class="login-screen">
    <div class="login-card">
      <div class="brand-symbol">∞</div>
      <h1>数据治理平台</h1>
      <p>全链路数据 · 统一治理门户</p>
      <p v-if="initializing">正在连接本地服务…</p>
      <form v-else @submit.prevent="login">
        <label>账号<input v-model="loginName" autocomplete="username" required /></label
        ><label
          >密码<input
            v-model="password"
            type="password"
            autocomplete="current-password"
            required /></label
        ><button class="primary" type="submit">登录平台</button>
      </form>
      <p v-if="!initializing" class="muted">{{ loginError || '请输入账号和密码登录' }}</p>
    </div>
  </div>
  <div v-else class="platform-shell">
    <header class="topbar">
      <RouterLink to="/home" class="brand"
        ><svg width="32" height="32" viewBox="0 0 40 40" aria-hidden="true">
          <ellipse
            cx="19"
            cy="16"
            rx="14"
            ry="8"
            transform="rotate(-25 19 16)"
            fill="none"
            stroke="#ffe29a"
            stroke-width="2"
          />
          <ellipse
            cx="22"
            cy="22"
            rx="14"
            ry="8"
            transform="rotate(65 22 22)"
            fill="none"
            stroke="#9fede6"
            stroke-width="2"
          />
          <ellipse
            cx="19"
            cy="20"
            rx="14"
            ry="8"
            transform="rotate(155 19 20)"
            fill="none"
            stroke="white"
            stroke-width="2"
          /></svg
        ><span>数据治理平台</span></RouterLink
      >
      <nav class="topnav" aria-label="平台模块">
        <RouterLink to="/home" :class="{ active: current?.group === 'home' }"
          ><Icon name="home" />首页</RouterLink
        ><RouterLink
          v-for="g in groups"
          :key="g.id"
          :to="pages.find((p) => p.group === g.id)!.path"
          :class="{ active: current?.group === g.id }"
          ><Icon :name="g.icon" />{{ g.title }}</RouterLink
        >
      </nav>
      <div class="account">
        <span class="avatar">{{ platform.user?.name?.slice(0, 1).toUpperCase() }}</span>
        <div>
          {{ platform.user?.name
          }}<small>{{ platform.user?.role === 'admin' ? '本地管理员' : '只读用户' }}</small>
        </div>
        <button class="logout" @click="logout">退出</button>
      </div>
    </header>
    <aside v-if="sidePages.length" class="sidebar">
      <div class="sidebar-title">
        {{ groups.find((g) => g.id === current?.group)?.title }}<small>DATA WORKSPACE</small>
      </div>
      <div v-for="section in sections" :key="section" class="nav-section">
        <div class="section-name">{{ section }}</div>
        <RouterLink
          v-for="p in sidePages.filter((p) => p.section === section)"
          :key="p.path"
          :to="p.path"
          ><span class="nav-dot" />{{ p.title }}</RouterLink
        >
      </div>
      <div class="sidebar-bottom">
        <span v-if="connectionState.online" class="online-dot" />
        {{
          connectionState.online === false
            ? '本地服务未连接'
            : connectionState.online
              ? '本地服务运行中'
              : '正在检查本地服务'
        }}
      </div>
    </aside>
    <main
      :class="[
        'main',
        { 'with-sidebar': sidePages.length, 'home-main': current?.group === 'home' },
      ]"
    >
      <div v-if="connectionState.online === false" class="error-banner" role="alert">
        本地服务未连接。请双击“启动项目.cmd”启动，恢复后重试。当前页面已填写的内容仍保留，请勿直接刷新整页。
      </div>
      <div v-if="updateAvailable" class="info-banner" role="status">
        平台已更新：当前页面 v{{ pageVersion }}，服务 v{{ platform.health.version }}。
        请先保存正在编辑的内容，再重新加载页面。
        <button @click="reloadPage">重新加载页面</button>
      </div>
      <div v-if="current?.group !== 'home'" class="breadcrumb">
        <RouterLink to="/home">工作首页</RouterLink><span>/</span
        >{{ groups.find((g) => g.id === current?.group)?.title }}<span>/</span>{{ current?.title
        }}<span class="environment">{{
          platform.health.databaseConfigured
            ? '已验证只读数据源'
            : '本地治理 · 支持多种数据库只读采集'
        }}</span>
      </div>
      <RouterView :key="route.path" />
    </main>
    <footer :class="{ 'with-sidebar': sidePages.length }">
      数据治理平台 · 本地工作空间
      <span>页面 v{{ pageVersion }} · 服务 v{{ platform.health.version || '—' }}</span>
    </footer>
  </div>
  <Transition name="toast"
    ><div v-if="platform.toast" :class="['toast', { error: platform.toastError }]" role="status">
      {{ platform.toast }}
    </div></Transition
  >
</template>
