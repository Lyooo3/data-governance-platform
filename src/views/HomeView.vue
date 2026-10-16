<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { list } from '../api/client'
import type { Entity } from '../api/client'
import { act, dateText, platform, refresh, statusText } from '../stores/platform'
import Icon from '../components/Icon.vue'
const assets = ref<Entity[]>([]),
  services = ref<Entity[]>([])
const resourceTab = ref('level')
const resourceGroups = computed(() => {
  const counts: Record<string, number> = {}
  for (const asset of assets.value) {
    const name =
      (resourceTab.value === 'level' ? asset.dataLevelName : asset.sourceSystem) || '未分类'
    counts[name] = (counts[name] || 0) + 1
  }
  return Object.entries(counts)
})
onMounted(() =>
  act(async () => {
    await refresh()
    assets.value = (await list('assets')).list
    services.value = (await list('services')).list
  }),
)
const published = computed(() => services.value.filter((s) => s.published).length)
const systems = computed(() =>
  Object.entries(
    assets.value.reduce((r: Record<string, number>, a) => {
      const k = a.sourceSystem || '未分类'
      r[k] = (r[k] || 0) + 1
      return r
    }, {}),
  ),
)
const stages = [
  {
    name: '数据标准',
    en: 'STANDARD',
    icon: 'standard',
    path: '/standard/elements',
    description: '数据元 · 代码集 · 限定词',
  },
  {
    name: '数据接入',
    en: 'CONNECT',
    icon: 'access',
    path: '/access/sources',
    description: '只读采集 · 原始库 · 元数据',
  },
  {
    name: '数据处理',
    en: 'PROCESS',
    icon: 'flow',
    path: '/develop/flows',
    description: '清洗 · 过滤 · 去重',
  },
  {
    name: '数据治理',
    en: 'GOVERN',
    icon: 'quality',
    path: '/quality/overview',
    description: '规则 · 检测 · 预警',
  },
  {
    name: '数据资产',
    en: 'CATALOG',
    icon: 'asset',
    path: '/asset/resources',
    description: '目录 · 分类 · 资源',
  },
  {
    name: '数据服务',
    en: 'SERVE',
    icon: 'service',
    path: '/service/manage',
    description: '发布 · 授权 · 查询',
  },
]
</script>
<template>
  <section class="home-hero">
    <div class="hero-inner">
      <div class="welcome">
        <span class="hero-avatar"><Icon name="user" :size="35" /></span>
        <div>
          <div class="hero-eyebrow">DATA GOVERNANCE PLATFORM</div>
          <h1>Hi，{{ platform.user?.name }}</h1>
          <p>欢迎使用一站式全链路数据治理平台</p>
        </div>
      </div>
      <div class="today-label">今日任务<br />执行情况</div>
      <div
        v-for="(m, i) in [
          { label: '任务总数', value: platform.summary.today.total },
          { label: '运行失败', value: platform.summary.today.failed },
          { label: '运行中', value: platform.summary.today.running },
          { label: '运行成功', value: platform.summary.today.success },
        ]"
        :key="m.label"
        class="hero-stat"
      >
        <span>{{ m.label }}</span
        ><strong :class="'stat-' + i">{{ m.value || 0 }}</strong>
      </div>
    </div>
  </section>
  <div class="home-content">
    <div class="workspace-note">
      <span class="online-dot" /> 本地工作空间已就绪
      <span class="note-divider">|</span> 支持常见数据库只读采集，治理使用本地原始库副本
      <RouterLink to="/access/raw">查看原始库 <Icon name="arrow" :size="14" /></RouterLink>
    </div>
    <div class="dashboard-grid">
      <section class="panel resource-panel">
        <h2 class="panel-title">资源情况 <span>RESOURCE</span></h2>
        <div class="resource-total">
          <small>资源已登记（个）</small><strong>{{ platform.summary.counts.assets || 0 }}</strong>
          <div class="aqua-line" />
        </div>
        <div class="mini-counts">
          <span
            >服务发布 <b>{{ published }}</b></span
          ><span
            >待处理预警 <b>{{ platform.summary.openAlerts || 0 }}</b></span
          >
        </div>
        <div class="panel-tabs">
          <button :class="{ selected: resourceTab === 'level' }" @click="resourceTab = 'level'">
            数据分级</button
          ><button :class="{ selected: resourceTab === 'source' }" @click="resourceTab = 'source'">
            数据组织
          </button>
        </div>
        <div v-for="[level, count] in resourceGroups" :key="level" class="level-card">
          <span>{{ level }}</span
          ><strong>{{ count }} 个资源</strong>
        </div>
        <div class="resource-links">
          <RouterLink to="/asset/resources">资源管理 <Icon name="arrow" /></RouterLink
          ><RouterLink to="/asset/catalogs">目录管理 <Icon name="arrow" /></RouterLink>
        </div>
      </section>
      <div class="center-panels">
        <section class="panel chain-panel">
          <h2 class="panel-title">全链路数据治理 <span>DATA LIFECYCLE</span></h2>
          <div class="lifecycle">
            <template v-for="(s, i) in stages" :key="s.name"
              ><RouterLink :to="s.path" class="stage"
                ><div class="stage-circle"><Icon :name="s.icon" :size="25" /></div>
                <strong>{{ s.name }}</strong
                ><small>{{ s.en }}</small>
                <p>{{ s.description }}</p></RouterLink
              >
              <div v-if="i < stages.length - 1" class="stage-arrow">››</div></template
            >
          </div>
          <div class="chain-support">
            <span><Icon name="quality" /> 统一规则约束</span
            ><span><Icon name="flow" /> 可视化流程编排</span
            ><span><Icon name="clock" /> 运行结果追踪</span>
          </div>
          <div class="chain-cta">
            <div>
              <strong>从样例开始，完成一次治理</strong>
              <p>读取 → 清洗 → 去重 → 质量检查 → 保存结果</p>
            </div>
            <RouterLink class="primary button" to="/develop/flows"
              >进入治理流程 <Icon name="arrow"
            /></RouterLink>
          </div>
        </section>
        <section class="panel">
          <h2 class="panel-title">
            最近任务 <span>RECENT RUNS</span
            ><RouterLink to="/develop/runs" class="panel-more">全部记录 →</RouterLink>
          </h2>
          <div v-if="!platform.runs.length" class="empty">
            <Icon name="flow" :size="35" /><strong>还没有运行记录</strong>
            <p>执行内置示例后，这里会展示真实的任务状态与结果。</p>
            <RouterLink to="/develop/flows" class="text-button">打开示例流程 →</RouterLink>
          </div>
          <div v-else class="recent-list">
            <RouterLink
              v-for="run in platform.runs.slice(0, 4)"
              :key="run.id"
              :to="'/develop/runs?run=' + run.id"
              ><span class="recent-icon"><Icon name="flow" /></span>
              <div>
                <strong>{{ run.name }}</strong
                ><small>{{ dateText(run.startedAt) }}</small>
              </div>
              <span :class="['badge', run.status]">{{ statusText[run.status] }}</span></RouterLink
            >
          </div>
        </section>
      </div>
      <div class="right-panels">
        <section class="panel">
          <h2 class="panel-title">数据标准情况 <span>STANDARD</span></h2>
          <div class="standard-head"><span>标准类型</span><span>已配置</span></div>
          <RouterLink
            v-for="s in [
              { label: '数据元', kind: 'elements', path: 'elements' },
              { label: '代码集', kind: 'dictionaries', path: 'dictionaries' },
              { label: '限定词', kind: 'qualifiers', path: 'qualifiers' },
              { label: '标准目录', kind: 'catalogs', path: '../asset/catalogs' },
            ]"
            :key="s.kind"
            :to="s.kind === 'catalogs' ? '/asset/catalogs' : '/standard/' + s.path"
            class="standard-row"
            ><span>{{ s.label }}</span
            ><strong
              >{{ platform.summary.counts[s.kind] || 0 }}<small> 条</small></strong
            ></RouterLink
          >
        </section>
        <section class="panel">
          <h2 class="panel-title">来源系统 <span>SOURCE</span></h2>
          <div v-for="[name, amount] in systems" :key="name" class="source-bar">
            <div>
              <span>{{ name }}</span
              ><b>{{ amount }}</b>
            </div>
            <div class="bar-track">
              <span :style="{ width: (amount / Math.max(1, assets.length)) * 100 + '%' }" />
            </div>
          </div>
          <p class="muted tiny">以上为资产登记信息，非数据库采集统计。</p>
        </section>
        <section class="panel quick-panel">
          <h2 class="panel-title">常用操作</h2>
          <RouterLink to="/quality/rules"
            ><Icon name="quality" />配置质量规则<Icon name="arrow" /></RouterLink
          ><RouterLink to="/quality/tasks"
            ><Icon name="play" />创建检测任务<Icon name="arrow" /></RouterLink
          ><a href="/docs" target="_blank" rel="noopener"
            ><Icon name="standard" />后端接口文档<Icon name="arrow"
          /></a>
        </section>
      </div>
    </div>
  </div>
</template>
