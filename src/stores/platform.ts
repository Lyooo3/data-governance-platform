import { reactive } from 'vue'
import { list, request } from '../api/client'
import type { Entity } from '../api/client'

export const platform = reactive({
  user: null as Entity | null,
  health: {} as Entity,
  summary: { counts: {}, runs: {}, today: {} } as Entity,
  rules: [] as Entity[],
  datasets: [] as Entity[],
  views: [] as Entity[],
  runs: [] as Entity[],
  toast: '',
  toastError: false,
  ready: false,
})
let toastTimer: ReturnType<typeof setTimeout>
export function notify(text: string, error = false) {
  platform.toast = text
  platform.toastError = error
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    platform.toast = ''
  }, 4500)
}
export async function act<T>(operation: () => Promise<T>): Promise<T | undefined> {
  try {
    return await operation()
  } catch (error) {
    notify(error instanceof Error ? error.message : '操作失败', true)
  }
}
export async function refresh() {
  const [summary, rules, datasets, runs, views] = await Promise.all([
    request('summary'),
    list('rules'),
    list('datasets'),
    request('runs?pageSize=500'),
    request('/api/local/records/views'),
  ])
  Object.assign(platform, {
    summary,
    rules: rules.list,
    datasets: datasets.list,
    runs: runs.list,
    views: views.list,
  })
}
export async function boot() {
  platform.health = await request('/api/health')
  try {
    platform.user = await request('/api/auth/me')
  } catch {
    platform.user = await request('/api/auth/local-session', 'POST', {})
  }
  await refresh()
  platform.ready = true
}
export const dateText = (value?: string) =>
  value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
export const statusText: Record<string, string> = {
  SUCCESS: '执行成功',
  FAILED: '执行失败',
  RUNNING: '正在执行',
  CANCELLED: '已取消',
  TIMED_OUT: '执行超时',
  INTERRUPTED: '执行中断',
  open: '待处理',
  resolved: '已处理',
  draft: '待配置',
  registered: '已登记',
  published: '已发布',
}
