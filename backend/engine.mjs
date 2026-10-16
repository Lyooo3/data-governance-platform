import { requireValue } from './store.mjs';
import { sourceRows, writeNewTable } from './connectors.mjs';

export const NODE_TYPES = ['source', 'select', 'clean', 'filter', 'dedupe', 'quality', 'output'];
export function validateWorkflow(workflow) {
  let nodes = workflow.nodes || workflow.gzlNodes, edges = workflow.edges || workflow.gzlLines;
  try { if (typeof nodes === 'string') nodes = JSON.parse(nodes); if (typeof edges === 'string') edges = JSON.parse(edges); }
  catch { throw new Error('画布节点或连线不是有效JSON'); }
  requireValue(Array.isArray(nodes) && nodes.length >= 2 && nodes.length <= 50, '流程需要2至50个节点');
  requireValue(Array.isArray(edges), '流程需要连线');
  nodes = nodes.map(node => ({ ...node, id: String(node.id || node.nodeId || ''), type: node.type || node.nodeType, config: node.config || {}, x: Math.min(1100,Math.max(0,Number(node.x)||0)), y: Math.min(330,Math.max(0,Number(node.y)||0)) }));
  const map = new Map(nodes.map(n => [n.id, n]));
  requireValue(map.size === nodes.length && nodes.every(n => n.id && NODE_TYPES.includes(n.type)), '节点ID重复或包含尚未支持的节点类型');
  const incoming = new Map(nodes.map(n => [n.id, []])), outgoing = new Map(nodes.map(n => [n.id, []]));
  for (const edge of edges) {
    requireValue(map.has(edge.source) && map.has(edge.target) && edge.source !== edge.target, '连线指向不存在的节点或节点自身');
    incoming.get(edge.target).push(edge.source); outgoing.get(edge.source).push(edge.target);
  }
  requireValue(nodes.filter(n => n.type === 'source').length === 1 && nodes.filter(n => n.type === 'output').length === 1, '本版流程需要一个数据源节点和一个结果节点');
  for (const node of nodes) {
    requireValue(incoming.get(node.id).length === (node.type === 'source' ? 0 : 1), '所有非数据源节点需连接一个上游节点；暂不支持多表合并');
    requireValue(outgoing.get(node.id).length === (node.type === 'output' ? 0 : 1), '请按顺序连接全部节点；本版执行线性流程');
  }
  const order = [], seen = new Set();
  let current = nodes.find(n => n.type === 'source').id;
  while (current) {
    requireValue(!seen.has(current), '流程中存在循环连线');
    seen.add(current); order.push(map.get(current)); current = outgoing.get(current)[0];
  }
  requireValue(order.length === nodes.length, '流程包含未连接的节点或循环');
  return { ...workflow, name: workflow.name || workflow.gzlName || '未命名流程', nodes, edges, order };
}

function fieldsExist(rows, fields) {
  if (!rows.length) return;
  requireValue(fields.every(f => Object.prototype.hasOwnProperty.call(rows[0], f)), '配置字段不在输入数据中：' + fields.filter(f => !(f in rows[0])).join('、'));
}
export function inspectQuality(rows, rules) {
  requireValue(Array.isArray(rules) && rules.length > 0 && rules.length <= 100, '质量节点需要1至100条规则');
  const details = [], invalid = new Set();
  for (const rule of rules) {
    fieldsExist(rows, [rule.field]);
    requireValue(['required','unique','regex','range','enum'].includes(rule.type), '不支持的质量规则类型');
    let pattern;
    if (rule.type === 'regex') {
      requireValue(typeof rule.pattern === 'string' && rule.pattern.length <= 200, '正则表达式无效或过长');
      try { pattern = new RegExp(rule.pattern, 'u'); } catch { throw new Error('正则表达式格式错误'); }
    }
    if (rule.type === 'enum') requireValue(Array.isArray(rule.values) && rule.values.length > 0, '枚举规则需要允许值');
    if (rule.type === 'range') {
      requireValue(rule.min != null || rule.max != null, '范围规则需要最小值或最大值');
      requireValue((rule.min == null || Number.isFinite(Number(rule.min))) && (rule.max == null || Number.isFinite(Number(rule.max))) && !(rule.min != null && rule.max != null && Number(rule.min) > Number(rule.max)), '范围规则上下限无效');
    }
    const frequencies = new Map();
    if (rule.type === 'unique') for (const row of rows) { const value = JSON.stringify(row[rule.field]); frequencies.set(value, (frequencies.get(value) || 0) + 1); }
    const failed = [];
    rows.forEach((row, index) => {
      const value = row[rule.field], empty = value == null || String(value).trim() === '';
      let passed;
      if (rule.type === 'required') passed = !empty;
      if (rule.type === 'unique') passed = !empty && frequencies.get(JSON.stringify(value)) === 1;
      if (rule.type === 'regex') passed = !empty && pattern.test(String(value));
      if (rule.type === 'range') passed = !empty && Number.isFinite(Number(value)) && (rule.min == null || Number(value) >= Number(rule.min)) && (rule.max == null || Number(value) <= Number(rule.max));
      if (rule.type === 'enum') passed = !empty && rule.values.some(x => String(x) === String(value));
      if (!passed) { failed.push(index); invalid.add(index); }
    });
    details.push({ id: rule.id, name: rule.name || `${rule.field} / ${rule.type}`, field: rule.field, type: rule.type, checked: rows.length, failed: failed.length, passed: rows.length - failed.length, passRate: rows.length ? (rows.length - failed.length) / rows.length : null, failedIndexes: failed.slice(0,100) });
  }
  return { checkedRows: rows.length, invalidRows: invalid.size, passedRows: rows.length - invalid.size, passRate: rows.length ? (rows.length - invalid.size) / rows.length : null, rules: details, invalidIndexes: [...invalid] };
}

export async function executeWorkflow(store, workflow, onStep = () => {}) {
  const graph = validateWorkflow(workflow), reports = [], steps = [];
  let rows = [], sourceCount = 0, lineage = null;
  for (const node of graph.order) {
    const started = Date.now(), inputRows = rows.length, c = node.config;
    onStep({ nodeId: node.id, label: node.label || node.type, status: 'RUNNING' });
    if (node.type === 'source') {
      rows = await sourceRows(store, c, 10000); sourceCount = rows.length;
      lineage = { sourceId: c.sourceId, table: c.table || null, queryUsed: Boolean(c.sql) };
    } else if (node.type === 'select') {
      const mappings = c.mappings || [];
      requireValue(Array.isArray(mappings) && mappings.length > 0 && mappings.every(m => typeof m.to === 'string' && m.to.trim()), '字段映射需要来源字段和目标字段');
      requireValue(new Set(mappings.map(m => m.to)).size === mappings.length, '目标字段名称不能重复');
      fieldsExist(rows, mappings.map(m => m.from));
      rows = rows.map(row => Object.fromEntries(mappings.map(m => [m.to, row[m.from]])));
    } else if (node.type === 'clean') {
      const fields = c.fields || [];
      requireValue(Array.isArray(fields) && fields.length, '请选择需要清洗的字段'); fieldsExist(rows, fields);
      requireValue(['trim','upper','lower','number','fill'].includes(c.operation), '请选择支持的清洗操作');
      rows = rows.map(row => { const result = { ...row }; for (const key of fields) {
        const value = row[key];
        if (c.operation === 'fill') { if (value == null || String(value).trim() === '') result[key] = c.value ?? ''; }
        else if (value != null) {
          if (c.operation === 'trim') result[key] = String(value).trim();
          if (c.operation === 'upper') result[key] = String(value).toUpperCase();
          if (c.operation === 'lower') result[key] = String(value).toLowerCase();
          if (c.operation === 'number') { const n = Number(String(value).trim()); result[key] = String(value).trim() !== '' && Number.isFinite(n) ? n : null; }
        }
      } return result; });
    } else if (node.type === 'filter') {
      fieldsExist(rows, [c.field]);
      requireValue(['eq','ne','contains','notEmpty','gt','lt'].includes(c.operator), '不支持的过滤条件');
      rows = rows.filter(row => {
        const value = row[c.field];
        if (c.operator === 'eq') return String(value) === String(c.value);
        if (c.operator === 'ne') return String(value) !== String(c.value);
        if (c.operator === 'contains') return value != null && String(value).includes(String(c.value));
        if (c.operator === 'notEmpty') return value != null && String(value).trim() !== '';
        if (c.operator === 'gt') return value != null && String(value).trim() !== '' && Number(value) > Number(c.value);
        return value != null && String(value).trim() !== '' && Number(value) < Number(c.value);
      });
    } else if (node.type === 'dedupe') {
      requireValue(Array.isArray(c.fields) && c.fields.length, '去重需要业务键字段'); fieldsExist(rows, c.fields);
      const seen = new Set(); rows = rows.filter(row => { const key = JSON.stringify(c.fields.map(k => row[k])); if (seen.has(key)) return false; seen.add(key); return true; });
    } else if (node.type === 'quality') {
      const rules = c.rules || (c.ruleIds || []).map(id => store.get('rules', id));
      requireValue(rules.every(Boolean), '质量规则已删除或不存在');
      const report = inspectQuality(rows, rules); reports.push({ ...report, nodeId: node.id });
      if (c.dropInvalid === true) { const invalid = new Set(report.invalidIndexes); rows = rows.filter((_, index) => !invalid.has(index)); }
    } else if (node.type === 'output') {
      if (c.sourceId) {
        requireValue(c.table, '输出到数据库需要新的目标表名');
        lineage = { ...lineage, output: await writeNewTable(store, c.sourceId, c.table, rows) };
      }
    }
    const step = { nodeId: node.id, label: node.label || node.type, type: node.type, inputRows, outputRows: rows.length, durationMs: Date.now() - started, status: 'SUCCESS' };
    steps.push(step); onStep(step);
  }
  return { rows, reports, steps, sourceCount, outputCount: rows.length, lineage };
}
