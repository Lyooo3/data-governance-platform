import { reactive } from 'vue'

export const connectionState = reactive({ online: null as boolean | null })

export type Entity = Record<string, any>
export interface Page {
  list: Entity[]
  total: number
  pageNum: number
  pageSize: number
}

export async function request<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(path.startsWith('/api/') ? path : '/api/governance/' + path, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    connectionState.online = true
  } catch {
    connectionState.online = false
    throw new Error(
      '无法连接本地治理平台服务。请双击“启动项目.cmd”启动；恢复后先刷新列表确认操作结果，再重试。',
    )
  }
  let result
  try {
    result = await response.json()
  } catch {
    throw new Error(`服务请求失败（${response.status}），请检查后端服务或稍后重试。`)
  }
  if (!response.ok || !result.success) throw new Error(result.message || '请求失败')
  return result.data as T
}

export const list = (kind: string) => request<Page>(kind + '?pageSize=500')
export const save = (kind: string, value: Entity) =>
  request<Entity>(kind + (value.id ? '/' + value.id : ''), value.id ? 'PUT' : 'POST', value)
export const remove = (kind: string, id: string) => request(kind + '/' + id, 'DELETE')
