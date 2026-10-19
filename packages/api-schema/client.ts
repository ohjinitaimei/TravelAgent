import type { components } from './schema'

export type Schema<K extends keyof components['schemas']> = components['schemas'][K]
export type PlanRequest = Schema<'PlanRequest'>
export type Task = Schema<'Task'>
export type TravelEvent = Schema<'Event'>
export type Itinerary = Schema<'Itinerary'>
export type Poi = Schema<'Poi'>
export type Draft = Schema<'Draft'>
export type Transport = (path: string, init?: { method?: string; body?: unknown; signal?: AbortSignal; headers?:Record<string,string> }) => Promise<unknown>
export type SubmitOptions = {idempotencyKey?:string}

function delay(ms:number, signal:AbortSignal) {
  return new Promise<void>((resolve,reject)=>{
    const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve()},ms)
    function abort(){clearTimeout(timer);reject(signal.reason)}
    if(signal.aborted) abort();else signal.addEventListener('abort',abort,{once:true})
  })
}

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
      headers: { ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }), ...init.headers },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    })
    const data = await response.json().catch(() => { throw new TravelApiError('invalid_response', '服务返回了无效响应', true) })
    if (!response.ok) {
      throw new TravelApiError(data.error?.code || 'http_error', data.error?.message || `请求失败 (${response.status})`, data.error?.retryable ?? (response.status>=500||response.status===429))
    }
    return data
    } catch(error) {
      if(controller.signal.aborted) throw controller.signal.reason
      if(error instanceof TypeError) throw new TravelApiError('network_error','无法连接服务，请检查网络后恢复连接',true)
      throw error
    } finally { clearTimeout(timer); init.signal?.removeEventListener('abort', abort) }
  }
}

export class TravelClient {
  constructor(private transport: Transport) {}
  private async get<T>(path: string, signal?: AbortSignal): Promise<T> { return await this.transport(path, { signal }) as T }
  private async post<T>(path: string, body?: unknown, options:SubmitOptions={}): Promise<T> { return await this.transport(path, { method: 'POST', body, headers:options.idempotencyKey?{'Idempotency-Key':options.idempotencyKey}:undefined }) as T }
  capabilities() { return this.get<Schema<'Capabilities'>>('/capabilities') }
  create(request: PlanRequest, options?:SubmitOptions) { return this.post<Task>('/tasks', request,options) }
  createDraft(request: Schema<'DraftRequest'>, options?:SubmitOptions) { return this.post<Task>('/drafts', request,options) }
  submission(key:string) {return this.get<Task>(`/submissions/${encodeURIComponent(key)}`)}
  retry(id:string, options?:SubmitOptions) {return this.post<Task>(`/tasks/${encodeURIComponent(id)}/retry`,undefined,options)}
  draft(id: string) { return this.get<Draft>(`/drafts/${encodeURIComponent(id)}`) }
  async clarifyDraft(id: string, request: Schema<'DraftClarificationRequest'>): Promise<Draft> {
    return await this.transport(`/drafts/${encodeURIComponent(id)}`, {method:'PATCH', body:request}) as Draft
  }
  task(id: string, signal?: AbortSignal) { return this.get<Task>(`/tasks/${encodeURIComponent(id)}`, signal) }
  cancel(id: string) { return this.post<Task>(`/tasks/${encodeURIComponent(id)}/cancel`) }
  events(id: string, after = 0, signal?: AbortSignal) { return this.get<Schema<'EventList'>>(`/tasks/${encodeURIComponent(id)}/events?after=${after}`, signal) }
  itineraries() { return this.get<Schema<'ItineraryList'>>('/itineraries') }
  itinerary(id: string) { return this.get<Itinerary>(`/itineraries/${encodeURIComponent(id)}`) }
  adjust(id: string, request: Schema<'EditRequest'>, options?:SubmitOptions) { return this.post<Task>(`/itineraries/${encodeURIComponent(id)}/adjust`, request,options) }
  search(keyword: string, city: string) { return this.get<Schema<'PoiList'>>(`/pois?${new URLSearchParams({keyword, city})}`) }
  detail(id: string) { return this.get<Poi>(`/pois/${encodeURIComponent(id)}`) }
  route(request: Schema<'RouteQuery'>) { return this.post<Schema<'Segment'>>('/routes', request) }

  /** Platform-neutral polling: uni-app can inject uni.request as transport. */
  async wait(id: string, onUpdate: (task: Task, events: TravelEvent[]) => void,
             options: { signal?: AbortSignal; intervalMs?: number; timeoutMs?: number; maxConsecutiveErrors?:number; retryDelayMs?:number; onConnection?:(state:'connected'|'reconnecting',attempt:number)=>void } = {}): Promise<Task> {
    const controller = new AbortController()
    const abort = () => controller.abort(options.signal?.reason)
    if (options.signal?.aborted) abort()
    else options.signal?.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(() => controller.abort(new TravelApiError('client_wait_timeout', '等待状态超时，任务仍可通过任务 ID 查询', true)), options.timeoutMs ?? 210_000)
    let cursor = 0
    let failures=0
    try {
    while (true) {
      controller.signal.throwIfAborted()
      try {
        const task = await this.task(id, controller.signal)
        const terminal=!['queued','running'].includes(task.status)
        onUpdate(task,[])
        let items:TravelEvent[]=[]
        try {items=(await this.events(id,cursor,controller.signal)).items}
        catch(error) {if(controller.signal.aborted||!terminal||!(error instanceof TravelApiError&&error.retryable)) throw error}
        controller.signal.throwIfAborted()
        cursor=items.at(-1)?.id||cursor
        onUpdate(task,items)
        failures=0;options.onConnection?.('connected',0)
        if(terminal) return task
        await delay(options.intervalMs??1000,controller.signal)
      } catch(error) {
        if(controller.signal.aborted) throw controller.signal.reason
        if(!(error instanceof TravelApiError&&error.retryable)) throw error
        failures+=1;options.onConnection?.('reconnecting',failures)
        if(failures>(options.maxConsecutiveErrors??4)) throw error
        await delay(Math.min((options.retryDelayMs??250)*2**(failures-1),4000),controller.signal)
      }
    }
    } finally { clearTimeout(timer); options.signal?.removeEventListener('abort', abort) }
  }
}
