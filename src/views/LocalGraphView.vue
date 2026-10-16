<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { local } from '../local/shared'
import type { Entity } from '../api/client'
import DataTable from '../components/DataTable.vue'
const route = useRoute(),
  graph = ref<Entity>({ nodes: [], edges: [], mappings: [] }),
  flows = ref<Entity[]>([]),
  selected = ref(''),
  detail = ref<Entity>(),
  error = ref('')
const nodes = computed<Entity[]>(() =>
  graph.value.nodes
    .slice(0, 80)
    .map((n: Entity, i: number) => ({
      ...n,
      x: 25 + (i % 3) * 245,
      y: 25 + Math.floor(i / 3) * 100,
    })),
)
const height = computed(() => Math.max(220, Math.ceil(nodes.value.length / 3) * 100 + 30))
function path(e: Entity) {
  const a = nodes.value.find((n) => n.id === e.source),
    b = nodes.value.find((n) => n.id === e.target)
  return a && b
    ? `M${a.x + 205},${a.y + 30} C${a.x + 225},${a.y + 30} ${b.x - 20},${b.y + 30} ${b.x},${b.y + 30}`
    : ''
}
async function load() {
  try {
    const [g, b] = await Promise.all([
      local('lineage' + (selected.value ? '?workflowId=' + selected.value : '')),
      local('bootstrap'),
    ])
    graph.value = g
    flows.value = b.workflows
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  }
}
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>{{ route.meta.title }}</h1>
      <p>从真实数据集、流程节点、字段映射、运行结果和服务关联生成本地血缘。</p>
    </div>
    <button @click="load">刷新</button>
  </div>
  <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
  <section class="panel">
    <div class="table-toolbar">
      <label
        >治理流程<select v-model="selected" @change="load">
          <option value="">全部流程</option>
          <option v-for="f in flows" :key="f.id" :value="f.id">{{ f.name }}</option>
        </select></label
      ><span>{{ graph.nodes.length }}个对象 · {{ graph.edges.length }}条关联</span>
    </div>
    <div class="local-graph-scroll">
      <svg width="760" :height="height" role="img" aria-label="本地数据血缘图">
        <path
          v-for="(e, i) in graph.edges"
          :key="i"
          :d="path(e)"
          fill="none"
          stroke="#82a6de"
          stroke-width="2"
        />
        <g v-for="n in nodes" :key="n.id">
          <rect :x="n.x" :y="n.y" width="205" height="66" rx="8" fill="#f1f6ff" stroke="#acc3ed" />
          <text :x="n.x + 12" :y="n.y + 24" fill="#315aa4" font-size="12">{{ n.kind }}</text>
          <text :x="n.x + 12" :y="n.y + 46" font-size="11" fill="#26364c">
            {{ n.label.slice(0, 16) }}{{ n.label.length > 16 ? '…' : '' }}
          </text>
        </g>
      </svg>
    </div>
    <p v-if="graph.nodes.length > 80" class="muted">图中展示前80个对象，完整关联见下表。</p>
    <DataTable
      :rows="graph.nodes"
      :columns="[
        { key: 'label', label: '对象' },
        { key: 'kind', label: '类型' },
      ]"
      ><template #actions="{ row }"
        ><button class="text-button" @click="detail = row">查看关联</button
        ><RouterLink v-if="row.path" :to="row.path">打开对象</RouterLink></template
      ></DataTable
    >
  </section>
  <section v-if="detail" class="panel">
    <h2>{{ detail.label }}</h2>
    <p
      v-for="(e, i) in graph.edges.filter(
        (e: Entity) => e.source === detail?.id || e.target === detail?.id,
      )"
      :key="i"
    >
      {{ graph.nodes.find((n: Entity) => n.id === e.source)?.label }} →
      {{ graph.nodes.find((n: Entity) => n.id === e.target)?.label }}
    </p>
    <button @click="detail = undefined">收起关联</button>
  </section>
  <section class="panel">
    <h2>字段级映射</h2>
    <DataTable
      :rows="graph.mappings"
      :columns="[
        { key: 'workflow', label: '流程' },
        { key: 'from', label: '原字段' },
        { key: 'to', label: '目标字段' },
      ]"
      empty="当前流程没有字段映射节点"
    />
  </section>
</template>
