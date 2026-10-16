import { request } from '../api/client'
import type { Entity } from '../api/client'
export const local = <T = any>(path: string, method = 'GET', body?: unknown) =>
  request<T>('/api/local/' + path, method, body)
export const statusLabels: Record<string, string> = {
  pending: '待处理',
  approved: '已通过',
  rejected: '已驳回',
  revoked: '已撤销',
  withdrawn: '已撤回',
  delivered: '已投递',
  failed: '失败',
  insert: '新增',
  update: '修改',
  delete: '删除',
}
export function parseJson(text: string, label: string) {
  try {
    return JSON.parse(text)
  } catch {
    throw new Error(label + '不是有效的JSON，请检查引号、逗号和括号。')
  }
}
export const commaList = (text: string) =>
  text
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
export function downloadJson(value: unknown, name: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' }),
  )
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name + '.json'
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export const metricsLabel: Record<string, string> = {
  total: '记录数',
  input: '输入记录',
  output: '输出记录',
  standards: '标准数',
  passed: '符合标准',
  failed: '未符合',
  matched: '已匹配',
  unmatched: '未匹配',
  timely: '及时',
  stale: '超期',
  invalid: '无效记录',
  future: '未来时间',
  nodes: '对象数',
  edges: '关系数',
  records: '关系记录',
  entities: '对象数',
  transactions: '交易笔数',
  totalAmount: '金额合计',
  insert: '新增',
  update: '修改',
  delete: '删除',
  rowCount: '记录数',
  received: '接收记录',
  saved: '保存记录',
}
export const tableColumns = (rows: Entity[]) =>
  Object.keys(rows[0] || {})
    .filter((k) => !['before', 'after', 'changes'].includes(k))
    .map((key) => ({ key, label: key }))
