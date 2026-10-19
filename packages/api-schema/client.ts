import type { components } from './schema'

export type Schema<K extends keyof components['schemas']> = components['schemas'][K]
export type PlanRequest = Schema<'PlanRequest'>
export type Task = Schema<'Task'>
export type TravelEvent = Schema<'Event'>
export type Itinerary = Schema<'Itinerary'>
export type Poi = Schema<'Poi'>
export type Draft = Schema<'Draft'>
export type Transport = (path: string, init?: { method?: string; body?: unknown; signal?: AbortSignal }) => Promise<unknown>

export class TravelApiError extends Error {
  constructor(public code: string, message: string, public retryable = false) { super(message) }
}

export function fetchTransport(base: string, timeoutMs = 15_000): Transport {
  return async (path, init = {}) => {
    const controller = new AbortController()
    const abort = () => controller.abort(init.signal?.reason)
    if (init.signal?.aborted) abort()
    else init.signal?.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(() => controller.abort(new TravelApiError('request_timeout', '接口请求超时，请检查服务连接', true)), timeoutMs)
    try {
    const response = await fetch(`${base}${path}`, {
      method: init.method || 'GET', signal: controller.signal,
      headers: init.body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    })
    const data = await response.json().catch(() => { throw new TravelApiError('invalid_response', '服务返回了无效响应', true) })
    if (!response.ok) {
      throw new TravelApiError(data.error?.code || 'http_error', data.error?.message || `请求失败 (${response.status})`, data.error?.retryable)
    }
    return data
    } finally { clearTimeout(timer); init.signal?.removeEventListener('abort', abort) }
  }
}

export class TravelClient {
  constructor(private transport: Transport) {}
  private async get<T>(path: string, signal?: AbortSignal): Promise<T> { return await this.transport(path, { signal }) as T }
  private async post<T>(path: string, body?: unknown): Promise<T> { return await this.transport(path, { method: 'POST', body }) as T }
  capabilities() { return this.get<Schema<'Capabilities'>>('/capabilities') }
  create(request: PlanRequest) { return this.post<Task>('/tasks', request) }
  createDraft(request: Schema<'DraftRequest'>) { return this.post<Task>('/drafts', request) }
  draft(id: string) { return this.get<Draft>(`/drafts/${encodeURIComponent(id)}`) }
  async clarifyDraft(id: string, request: Schema<'DraftClarificationRequest'>): Promise<Draft> {
    return await this.transport(`/drafts/${encodeURIComponent(id)}`, {method:'PATCH', body:request}) as Draft
  }
  task(id: string, signal?: AbortSignal) { return this.get<Task>(`/tasks/${encodeURIComponent(id)}`, signal) }
  cancel(id: string) { return this.post<Task>(`/tasks/${encodeURIComponent(id)}/cancel`) }
  events(id: string, after = 0, signal?: AbortSignal) { return this.get<Schema<'EventList'>>(`/tasks/${encodeURIComponent(id)}/events?after=${after}`, signal) }
  itineraries() { return this.get<Schema<'ItineraryList'>>('/itineraries') }
  itinerary(id: string) { return this.get<Itinerary>(`/itineraries/${encodeURIComponent(id)}`) }
  adjust(id: string, request: Schema<'EditRequest'>) { return this.post<Task>(`/itineraries/${encodeURIComponent(id)}/adjust`, request) }
  search(keyword: string, city: string) { return this.get<Schema<'PoiList'>>(`/pois?${new URLSearchParams({keyword, city})}`) }
  detail(id: string) { return this.get<Poi>(`/pois/${encodeURIComponent(id)}`) }
  route(request: Schema<'RouteQuery'>) { return this.post<Schema<'Segment'>>('/routes', request) }

  /** Platform-neutral polling: uni-app can inject uni.request as transport. */
  async wait(id: string, onUpdate: (task: Task, events: TravelEvent[]) => void,
             options: { signal?: AbortSignal; intervalMs?: number; timeoutMs?: number } = {}): Promise<Task> {
    const controller = new AbortController()
    const abort = () => controller.abort(options.signal?.reason)
    if (options.signal?.aborted) abort()
    else options.signal?.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(() => controller.abort(new TravelApiError('client_wait_timeout', '等待状态超时，任务仍可通过任务 ID 查询', true)), options.timeoutMs ?? 210_000)
    let cursor = 0
    try {
    while (true) {
      controller.signal.throwIfAborted()
      const task = await this.task(id, controller.signal)
      const events = await this.events(id, cursor, controller.signal)
      controller.signal.throwIfAborted()
      cursor = events.items.at(-1)?.id || cursor
      onUpdate(task, events.items)
      if (!['queued', 'running'].includes(task.status)) return task
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => { controller.signal.removeEventListener('abort', abort); resolve() }, options.intervalMs ?? 1000)
        function abort() { clearTimeout(timer); reject(controller.signal.reason) }
        if (controller.signal.aborted) abort()
        else controller.signal.addEventListener('abort', abort, { once: true })
      })
    }
    } finally { clearTimeout(timer); options.signal?.removeEventListener('abort', abort) }
  }
}
