<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { list } from '../api/client'
import type { Entity } from '../api/client'
import { act, dateText, platform, refresh } from '../stores/platform'
import Icon from '../components/Icon.vue'
const route = useRoute(),
  records = ref<Entity[]>([])
const group = computed(() => (route.meta.page as Entity).group)
const latest = computed(() => platform.summary.latestRun)
const report = computed(() => latest.value?.reports?.at(-1))
const cards = computed(() =>
  group.value === 'quality'
    ? [
        { label: '质量规则', value: platform.summary.counts.rules, icon: 'quality' },
        { label: '检测任务', value: platform.summary.counts.qualityTasks, icon: 'play' },
        { label: '历史运行', value: platform.summary.runs.total, icon: 'flow' },
        { label: '待处理预警', value: platform.summary.openAlerts, icon: 'bell' },
      ]
    : group.value === 'standard'
      ? ['elements', 'qualifiers', 'dictionaries', 'catalogs'].map((k, i) => ({
          label: ['数据元', '限定词', '代码集', '标准目录'][i],
          value: platform.summary.counts[k],
          icon: 'standard',
        }))
      : group.value === 'service'
        ? [
            { label: '已登记服务', value: records.value.length, icon: 'service' },
            {
              label: '已发布',
              value: records.value.filter((r) => r.published).length,
              icon: 'check',
            },
            {
              label: '未发布',
              value: records.value.filter((r) => !r.published).length,
              icon: 'clock',
            },
            { label: '可用数据集', value: platform.datasets.length, icon: 'database' },
          ]
        : [
            { label: '资源登记', value: platform.summary.counts.assets, icon: 'asset' },
            { label: '标准目录', value: platform.summary.counts.catalogs, icon: 'standard' },
            { label: '样例数据集', value: platform.datasets.length, icon: 'database' },
            { label: '元数据配置', value: platform.summary.counts.tables, icon: 'access' },
          ],
)
async function load() {
  await refresh()
  records.value = (await list(group.value === 'service' ? 'services' : 'assets')).list
}
onMounted(() => act(load))
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>{{ route.meta.title }}</h1>
      <p>配置与运行数据来自本地后端，所有统计随操作更新。</p>
    </div>
    <button @click="act(load)"><Icon name="refresh" />刷新</button>
  </div>
  <div class="metric-grid">
    <section v-for="card in cards" :key="card.label" class="panel metric-card">
      <span class="metric-icon"><Icon :name="card.icon" :size="25" /></span>
      <div>
        <small>{{ card.label }}</small
        ><strong>{{ card.value || 0 }}<span> 个</span></strong>
      </div>
    </section>
  </div>
  <template v-if="group === 'quality'"
    ><div class="overview-grid">
      <section class="panel">
        <h2 class="panel-title">最近一次成功检测 <span>QUALITY REPORT</span></h2>
        <div v-if="report" class="quality-summary">
          <div class="quality-ring" :style="{ '--rate': (report.passRate ?? 0) + '%' }">
            <div>
              <strong
                >{{ report.passRate ?? '—' }}<small v-if="report.passRate != null">%</small></strong
              ><span>记录合格率</span>
            </div>
          </div>
          <div>
            <h3>{{ latest.name }}</h3>
            <p class="muted">{{ dateText(latest.finishedAt) }}</p>
            <div class="quality-numbers">
              <span
                >检测记录 <b>{{ report.total }}</b></span
              ><span
                >合格记录 <b>{{ report.validRows }}</b></span
              ><span
                >问题记录 <b class="red">{{ report.invalidRows }}</b></span
              >
            </div>
            <RouterLink :to="'/develop/runs?run=' + latest.id" class="text-button"
              >查看完整报告 →</RouterLink
            >
          </div>
        </div>
        <div v-else class="empty">尚无检测报告，请先执行流程或质量任务。</div>
        <p class="muted tiny">
          统计范围为最近一次成功运行的最后一个质量节点，历史预警按实际记录累计。
        </p>
      </section>
      <section class="panel">
        <h2 class="panel-title">质量治理操作</h2>
        <div class="operation-list">
          <RouterLink to="/quality/rules"
            ><Icon name="quality" />定义检测规则<span
              >非空、唯一、范围、格式、枚举 →</span
            ></RouterLink
          ><RouterLink to="/quality/tasks"
            ><Icon name="play" />执行自定义质量任务<span>选择样例和规则 →</span></RouterLink
          ><RouterLink to="/develop/flows"
            ><Icon name="flow" />编排治理流程<span>清洗、去重、检查、输出 →</span></RouterLink
          ><RouterLink to="/quality/alerts"
            ><Icon name="bell" />查看与处理预警<span>问题追踪、记录处理说明 →</span></RouterLink
          >
        </div>
      </section>
    </div>
    <section v-if="report" class="panel">
      <h2 class="panel-title">规则检查结果</h2>
      <table>
        <thead>
          <tr>
            <th>规则名称</th>
            <th>检查字段</th>
            <th>记录数</th>
            <th>问题数</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in report.rules" :key="r.id">
            <td>{{ r.name }}</td>
            <td class="mono">{{ r.field }}</td>
            <td>{{ r.total }}</td>
            <td>{{ r.failed }}</td>
            <td>
              <span :class="['badge', r.failed ? 'FAILED' : 'SUCCESS']">{{
                r.failed ? '存在问题' : '通过'
              }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section></template
  >
  <section v-else-if="group === 'system'" class="panel environment-panel">
    <h2 class="panel-title">服务信息</h2>
    <dl>
      <dt>前端</dt>
      <dd>Vue 3 / TypeScript / Vite</dd>
      <dt>后端</dt>
      <dd>FastAPI / Python</dd>
      <dt>平台数据库</dt>
      <dd>SQLite · .data-v3/platform.sqlite3 · 已创建业务表</dd>
      <dt>外部业务数据库</dt>
      <dd>支持常见关系数据库、MongoDB及ClickHouse，连接能力见数据接入；治理读取本地副本</dd>
      <dt>运行限制</dt>
      <dd>单数据源、线性流程；最多10,000行、45秒、2个并发任务</dd>
      <dt>接口文档</dt>
      <dd><a href="/docs" target="_blank" rel="noopener">打开FastAPI接口文档 →</a></dd>
    </dl>
  </section>
  <section v-else class="panel">
    <h2 class="panel-title">
      {{
        group === 'standard'
          ? '标准管理链路'
          : group === 'service'
            ? '服务发布流程'
            : '资源组织与数据地图'
      }}
    </h2>
    <div class="overview-link-grid">
      <RouterLink
        v-for="p in group === 'standard'
          ? [
              {
                path: '/standard/elements',
                label: '数据元',
                detail: '定义字段名称、类型与业务语义',
              },
              {
                path: '/standard/dictionaries',
                label: '代码集',
                detail: '维护代码和名称之间的对应关系',
              },
              { path: '/quality/rules', label: '质量规则', detail: '将规范转换成实际检测条件' },
            ]
          : group === 'service'
            ? [
                {
                  path: '/service/register',
                  label: '注册服务',
                  detail: '选择数据集、运行结果或本地视图',
                },
                {
                  path: '/service/manage',
                  label: '发布API',
                  detail: '设置字段白名单并生成访问密钥',
                },
                { path: '/system/audit', label: '调用审计', detail: '查看真实服务查询记录' },
              ]
            : [
                { path: '/asset/catalogs', label: '标准目录', detail: '组织资源分类和目录配置' },
                {
                  path: '/asset/resources',
                  label: '数据资源',
                  detail: '维护来源、分级和数据集关联',
                },
                { path: '/access/preview', label: '数据探索', detail: '查看样例字段及记录内容' },
              ]"
        :key="p.path"
        :to="p.path"
        ><Icon name="asset" :size="30" />
        <h3>{{ p.label }}</h3>
        <p>{{ p.detail }}</p>
        <span>进入管理 →</span></RouterLink
      >
    </div>
    <p class="muted">当前展示本地登记与治理结果，数据库采集的完整快照在“本地原始库”查看。</p>
  </section>
</template>
