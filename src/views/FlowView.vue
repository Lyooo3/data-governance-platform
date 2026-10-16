<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { list, request, save } from '../api/client'
import type { Entity } from '../api/client'
import { act, notify, platform, refresh } from '../stores/platform'
import Icon from '../components/Icon.vue'
const route = useRoute(),
  router = useRouter(),
  flows = ref<Entity[]>([]),
  flow = ref<Entity>({ name: '新治理流程', nodes: [], edges: [] }),
  selected = ref(''),
  connecting = ref(''),
  busy = ref(false),
  canvas = ref<HTMLElement>(),
  moved = ref(false)
const canWrite = computed(() => platform.user?.role === 'admin')
const node = computed<Entity | undefined>(() =>
  flow.value.nodes.find((n: Entity) => n.id === selected.value),
)
const palette = [
  {
    type: 'source',
    label: '读取数据',
    description: '选择本地治理数据集',
    icon: 'database',
    color: 'blue',
  },
  {
    type: 'select',
    label: '字段映射',
    description: '选择字段并重命名',
    icon: 'standard',
    color: 'purple',
  },
  {
    type: 'clean',
    label: '字段清洗',
    description: '空格、大小写、空值',
    icon: 'access',
    color: 'teal',
  },
  {
    type: 'filter',
    label: '条件过滤',
    description: '保留符合条件的记录',
    icon: 'settings',
    color: 'amber',
  },
  {
    type: 'dedupe',
    label: '业务键去重',
    description: '按一个或多个字段去重',
    icon: 'asset',
    color: 'purple',
  },
  {
    type: 'quality',
    label: '质量检查',
    description: '执行规则，生成问题报告',
    icon: 'quality',
    color: 'teal',
  },
  {
    type: 'output',
    label: '保存结果',
    description: '结果保存到平台数据库',
    icon: 'service',
    color: 'blue',
  },
]
const boardWidth = computed(() =>
  Math.max(1140, ...flow.value.nodes.map((n: Entity) => Number(n.x || 0) + 220)),
)
const boardHeight = computed(() =>
  Math.max(450, ...flow.value.nodes.map((n: Entity) => Number(n.y || 0) + 150)),
)
const selectedId = ref('')
const clone = (v: any) => JSON.parse(JSON.stringify(v))
async function load() {
  flows.value = (await list('workflows')).list
  await refresh()
  const dataset = platform.datasets.find((d) => d.id === route.query.dataset)
  if (dataset) {
    const sample = (await request('datasets/' + dataset.id + '/rows?pageSize=1')).list[0] || {}
    const textFields = Object.keys(sample).filter((k) => typeof sample[k] === 'string')
    flow.value = {
      name: dataset.name + '-治理流程',
      nodes: [
        {
          id: 'read',
          type: 'source',
          label: '读取治理副本',
          x: 30,
          y: 140,
          config: { datasetId: dataset.id },
        },
        {
          id: 'clean',
          type: 'clean',
          label: '清理文本空格',
          x: 245,
          y: 140,
          config: { fields: textFields, operation: 'trim' },
        },
        { id: 'output', type: 'output', label: '保存治理结果', x: 460, y: 140, config: {} },
      ],
      edges: [
        { source: 'read', target: 'clean' },
        { source: 'clean', target: 'output' },
      ],
    }
    if (!textFields.length) {
      flow.value.nodes = flow.value.nodes.filter((n: Entity) => n.id !== 'clean')
      flow.value.edges = [{ source: 'read', target: 'output' }]
    }
    selectedId.value = ''
    return
  }
  if (flows.value.length)
    choose(flows.value.find((f) => f.id === selectedId.value)?.id || flows.value[0]!.id)
}
function choose(id: string) {
  const value = flows.value.find((f) => f.id === id)
  if (value) {
    flow.value = clone(value)
    selectedId.value = id
    selected.value = ''
    connecting.value = ''
  }
}
onMounted(() => {
  act(load)
  document.addEventListener('pointermove', pointerMove)
  document.addEventListener('pointerup', pointerUp)
})
onUnmounted(() => {
  document.removeEventListener('pointermove', pointerMove)
  document.removeEventListener('pointerup', pointerUp)
})
function add(type: string, x?: number, y?: number) {
  if (!canWrite.value) return
  const p = palette.find((p) => p.type === type)
  if (!p) return
  const id = crypto.randomUUID()
  flow.value.nodes.push({
    id,
    type,
    label: p.label,
    x: x ?? 30 + flow.value.nodes.length * 215,
    y: y ?? 140,
    config:
      type === 'source'
        ? { datasetId: platform.datasets[0]?.id }
        : type === 'quality'
          ? { ruleIds: [], dropInvalid: false }
          : type === 'clean'
            ? { fields: [], operation: 'trim' }
            : type === 'dedupe'
              ? { fields: [] }
              : type === 'select'
                ? { mappings: [] }
                : type === 'filter'
                  ? { operator: 'eq' }
                  : {},
  })
  selected.value = id
}
function drop(event: DragEvent) {
  event.preventDefault()
  const rect = canvas.value!.getBoundingClientRect()
  add(
    event.dataTransfer!.getData('text/plain'),
    Math.max(10, event.clientX - rect.left - 80),
    Math.max(10, event.clientY - rect.top - 30),
  )
}
let dragging: { id: string; x: number; y: number; originalX: number; originalY: number } | undefined
function startMove(event: PointerEvent, n: Entity) {
  selected.value = n.id
  if (!canWrite.value || (event.target as HTMLElement).closest('button')) return
  dragging = { id: n.id, x: event.clientX, y: event.clientY, originalX: n.x, originalY: n.y }
  moved.value = false
  event.preventDefault()
}
function pointerMove(event: PointerEvent) {
  if (!dragging) return
  const n = flow.value.nodes.find((n: Entity) => n.id === dragging!.id)
  if (Math.abs(event.clientX - dragging.x) + Math.abs(event.clientY - dragging.y) > 3)
    moved.value = true
  n.x = Math.min(3000, Math.max(10, dragging.originalX + event.clientX - dragging.x))
  n.y = Math.min(1500, Math.max(10, dragging.originalY + event.clientY - dragging.y))
}
function pointerUp() {
  dragging = undefined
}
function connect(target: string) {
  if (!connecting.value) {
    notify('先点击上游节点的“连出”')
    return
  }
  if (target === connecting.value) {
    notify('不能连接节点自身', true)
    return
  }
  flow.value.edges = flow.value.edges.filter(
    (e: Entity) => e.source !== connecting.value && e.target !== target,
  )
  flow.value.edges.push({ source: connecting.value, target })
  connecting.value = ''
  notify('连线已添加，保存时将检查完整流程')
}
function edgePath(edge: Entity) {
  const a = flow.value.nodes.find((n: Entity) => n.id === edge.source),
    b = flow.value.nodes.find((n: Entity) => n.id === edge.target)
  if (!a || !b) return ''
  const x1 = a.x + 184,
    y1 = a.y + 62,
    x2 = b.x,
    y2 = b.y + 62
  return `M${x1},${y1} C${x1 + 55},${y1} ${x2 - 55},${y2} ${x2},${y2}`
}
function updateFields(event: Event) {
  if (node.value)
    node.value.config.fields = (event.target as HTMLInputElement).value
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean)
}
function updateMappings(event: Event) {
  if (node.value)
    node.value.config.mappings = (event.target as HTMLTextAreaElement).value
      .split('\n')
      .filter(Boolean)
      .map((line) => {
        const [from, to] = line.split(/→|->/)
        return { from: from?.trim(), to: to?.trim() }
      })
}
async function persist() {
  const value = await save('workflows', clone(flow.value))
  flow.value = value
  selectedId.value = value.id
  flows.value = (await list('workflows')).list
  return value
}
async function saveFlow() {
  busy.value = true
  await act(async () => {
    await persist()
    notify('流程已保存')
  })
  busy.value = false
}
async function run() {
  busy.value = true
  await act(async () => {
    const value = await persist(),
      result = await request('workflows/' + value.id + '/run', 'POST', {})
    router.push('/develop/runs?run=' + result.id)
  })
  busy.value = false
}
function deleteNode() {
  const id = selected.value
  flow.value.nodes = flow.value.nodes.filter((n: Entity) => n.id !== id)
  flow.value.edges = flow.value.edges.filter((e: Entity) => e.source !== id && e.target !== id)
  selected.value = ''
}
function newFlow() {
  flow.value = { name: '新治理流程', nodes: [], edges: [] }
  selected.value = ''
  selectedId.value = ''
  connecting.value = ''
}
function beginConnection(id: string) {
  connecting.value = id
  notify('点击下游节点的连入')
}
function clearEdges() {
  flow.value.edges = flow.value.edges.filter(
    (e: Entity) => e.source !== selected.value && e.target !== selected.value,
  )
}
function paletteDrag(event: DragEvent, type: string) {
  event.dataTransfer?.setData('text/plain', type)
}
</script>
<template>
  <div class="page-heading">
    <div>
      <h1>治理流程</h1>
      <p>拖入节点、配置参数并连接顺序，后端执行真实的数据处理。</p>
    </div>
    <div class="button-group">
      <button v-if="canWrite" @click="newFlow"><Icon name="plus" />新建流程</button
      ><button v-if="canWrite" :disabled="busy" @click="saveFlow">保存配置</button
      ><button v-if="canWrite" class="primary" :disabled="busy" @click="run">
        <Icon name="play" />执行流程
      </button>
    </div>
  </div>
  <section class="panel flow-panel">
    <div class="flow-toolbar">
      <label
        >流程<select v-model="selectedId" aria-label="选择流程" @change="choose(selectedId)">
          <option value="">新流程</option>
          <option v-for="f in flows" :key="f.id" :value="f.id">{{ f.name }}</option>
        </select></label
      ><input
        v-model="flow.name"
        aria-label="流程名称"
        :disabled="!canWrite"
        class="flow-name"
      /><span>{{ flow.nodes.length }} 个节点 · {{ flow.edges.length }} 条连线</span>
    </div>
    <div class="flow-workspace">
      <aside class="palette">
        <h3>治理节点</h3>
        <p>拖入画布，或点击添加</p>
        <button
          v-for="p in palette"
          :key="p.type"
          :draggable="canWrite"
          :disabled="!canWrite"
          @dragstart="paletteDrag($event, p.type)"
          @click="add(p.type)"
        >
          <span :class="['node-type-icon', p.color]"><Icon :name="p.icon" /></span
          ><span
            ><strong>{{ p.label }}</strong
            ><small>{{ p.description }}</small></span
          ><span class="drag-dots">⠿</span>
        </button>
        <div class="palette-tip">
          一个读取节点、一个输出节点<br />按顺序连接全部节点<br />当前支持线性流程
        </div>
      </aside>
      <div class="canvas-scroll">
        <div
          ref="canvas"
          class="flow-canvas"
          :style="{ width: boardWidth + 'px', height: boardHeight + 'px' }"
          @dragover.prevent
          @drop="drop"
        >
          <svg class="edge-layer" :width="boardWidth" :height="boardHeight">
            <defs>
              <marker
                id="arrowhead"
                markerWidth="7"
                markerHeight="7"
                refX="6"
                refY="3.5"
                orient="auto"
              >
                <path d="M0,0 L7,3.5 L0,7" fill="#6990dd" />
              </marker>
            </defs>
            <path
              v-for="(edge, i) in flow.edges"
              :key="i"
              :d="edgePath(edge)"
              fill="none"
              stroke="#6990dd"
              stroke-width="2"
              marker-end="url(#arrowhead)"
            />
          </svg>
          <div v-if="!flow.nodes.length" class="canvas-empty">
            <Icon name="flow" :size="45" />
            <h3>创建你的数据治理流程</h3>
            <p>从左侧添加“读取数据”节点开始</p>
          </div>
          <article
            v-for="n in flow.nodes"
            :key="n.id"
            :class="['flow-node', { selected: selected === n.id, connecting: connecting === n.id }]"
            :style="{ left: n.x + 'px', top: n.y + 'px' }"
            @pointerdown="startMove($event, n)"
            @click="selected = n.id"
          >
            <div class="node-heading">
              <span :class="['node-type-icon', palette.find((p) => p.type === n.type)?.color]"
                ><Icon :name="palette.find((p) => p.type === n.type)?.icon || 'flow'" /></span
              ><strong>{{ n.label }}</strong>
            </div>
            <p>
              {{
                n.type === 'source'
                  ? platform.datasets.find((d) => d.id === n.config.datasetId)?.name ||
                    '请选择数据集'
                  : n.type === 'quality'
                    ? (n.config.ruleIds?.length || 0) + ' 条质量规则'
                    : palette.find((p) => p.type === n.type)?.description
              }}
            </p>
            <div class="node-ports">
              <button
                v-if="n.type !== 'source'"
                :disabled="!canWrite"
                :aria-label="n.label + '连入'"
                @click.stop="connect(n.id)"
              >
                ● 连入</button
              ><span v-else /><button
                v-if="n.type !== 'output'"
                :disabled="!canWrite"
                :aria-label="n.label + '连出'"
                @click.stop="beginConnection(n.id)"
              >
                连出 ●
              </button>
            </div>
          </article>
        </div>
      </div>
      <aside class="node-properties">
        <h3>节点参数</h3>
        <div v-if="!node" class="empty">
          <Icon name="settings" :size="30" />点击画布节点<br />设置处理参数
        </div>
        <template v-else
          ><label>节点名称<input v-model="node.label" :disabled="!canWrite" /></label
          ><template v-if="node.type === 'source'"
            ><label
              >数据集<select v-model="node.config.datasetId" :disabled="!canWrite">
                <option v-for="d in platform.datasets" :key="d.id" :value="d.id">
                  {{ d.name }}
                </option>
              </select></label
            >
            <p class="muted">
              治理读取本地数据集，包括从原始库创建的副本；结果不回写远程库。
            </p></template
          ><template v-if="['clean', 'dedupe'].includes(node.type)"
            ><label
              >字段名（逗号分隔）<input
                :value="(node.config.fields || []).join(',')"
                :disabled="!canWrite"
                placeholder="org_name"
                @input="updateFields" /></label></template
          ><template v-if="node.type === 'clean'"
            ><label
              >清洗方式<select v-model="node.config.operation" :disabled="!canWrite">
                <option value="trim">去除首尾空格</option>
                <option value="upper">转为大写</option>
                <option value="lower">转为小写</option>
                <option value="number">转为数字</option>
                <option value="fill">填充空值</option>
              </select></label
            ><label v-if="node.config.operation === 'fill'"
              >填充值<input v-model="node.config.value" :disabled="!canWrite" /></label></template
          ><label v-if="node.type === 'select'"
            >字段映射（原字段 → 目标字段）<textarea
              :value="
                (node.config.mappings || []).map((m: Entity) => m.from + ' → ' + m.to).join('\n')
              "
              rows="6"
              :disabled="!canWrite"
              @input="updateMappings"
            /></label
          ><template v-if="node.type === 'filter'"
            ><label>过滤字段<input v-model="node.config.field" :disabled="!canWrite" /></label
            ><label
              >条件<select v-model="node.config.operator" :disabled="!canWrite">
                <option value="eq">等于</option>
                <option value="ne">不等于</option>
                <option value="contains">包含</option>
                <option value="notEmpty">非空</option>
                <option value="gt">大于</option>
                <option value="lt">小于</option>
              </select></label
            ><label
              >比较值<input v-model="node.config.value" :disabled="!canWrite" /></label></template
          ><template v-if="node.type === 'quality'"
            ><p>选择质量规则</p>
            <label v-for="r in platform.rules" :key="r.id" class="checkbox-label"
              ><input
                v-model="node.config.ruleIds"
                type="checkbox"
                :value="r.id"
                :disabled="!canWrite"
              />{{ r.name }}</label
            ><label class="checkbox-label"
              ><input
                v-model="node.config.dropInvalid"
                type="checkbox"
                :disabled="!canWrite"
              />排除不合格记录</label
            >
            <p class="muted">未勾选时保留问题记录，生成质量报告。</p></template
          >
          <p v-if="node.type === 'output'" class="muted">
            保存到SQLite平台数据库，可分页查看和下载CSV。不会写入业务数据库。
          </p>
          <div v-if="canWrite" class="node-property-actions">
            <button @click="clearEdges">清除相关连线</button
            ><button class="danger" @click="deleteNode">删除节点</button>
          </div></template
        >
      </aside>
    </div>
    <div class="canvas-footer">
      <span>{{
        connecting ? '正在连线：请点击下游节点的“连入”' : '拖动节点可调整位置，点击节点可编辑参数'
      }}</span
      ><span>执行上限：10,000行 / 45秒</span>
    </div>
  </section>
</template>
