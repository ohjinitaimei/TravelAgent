<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api, apiBase, type Draft, type Itinerary, type PlanRequest, type Poi, type Schema, type Task, type TravelEvent } from './api'
import RouteMap from './components/RouteMap.vue'
import { readSession, restoreForm, writeSession } from './session'
import { userPrices } from './editor'
import RequestAssistant from './components/RequestAssistant.vue'
import { draftForm } from './draft'

type Tab = 'plan' | 'explore' | 'saved' | 'budget'
const tabs = ['plan', 'explore', 'saved', 'budget'] as const
const initialTab = location.hash.slice(1)
const tab = ref<Tab>(tabs.includes(initialTab as Tab) ? initialTab as Tab : 'plan')
const session = readSession()
const today = new Date()
const localDate = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`
const form = reactive<PlanRequest>(restoreForm({ city: '', query: '', start_date: localDate, days: 2, stops_per_day: 3, day_start: '09:00', day_end: '18:00', stay_minutes: 60, mode: 'walking', budget: null, user_prices: {} }, session.form))
const capability = ref<Schema<'Capabilities'> | null>(null)
const error = ref(''), notice = ref(''), busy = ref(false)
const task = ref<Task | null>(null), events = ref<TravelEvent[]>([])
const itinerary = ref<Itinerary | null>(null), saved = ref<Itinerary[]>([])
const draft = ref<Draft|null>(null)
const draftConflict = ref(false)
const selectedDay = ref(0), selectedPoi = ref<Poi | null>(null)
const results = ref<Poi[]>([]), searching = ref(false), loadingDetail = ref(false)
const keyword = ref(''), searchCity = ref('')
const editing = ref(false), editIds = ref<string[][]>([]), editPrices = reactive<Record<string,string|number>>({})
const optimize = ref(false), editStay = ref(60), addDay = ref(0)
const editDurations = reactive<Record<string, number>>({}), moveDays = reactive<Record<string,number>>({})
const addedPois = reactive<Record<string,Poi>>({})
const editConstraints = reactive({start_date:localDate, day_start:'09:00', day_end:'18:00', mode:'walking' as 'walking'|'driving', budget:null as number|null})
const restoring = ref(false)
let stream: EventSource | null = null, controller: AbortController | null = null
const active = computed(() => restoring.value || ['queued','running'].includes(task.value?.status || ''))
const day = computed(() => itinerary.value?.days[selectedDay.value])
const statusLabels: Record<string,string> = { queued:'排队中', running:'规划中', succeeded:'已完成', failed:'失败', cancelled:'已取消', timed_out:'已超时' }
const nav = [{id:'plan',icon:'⌘',label:'行程工作台'}, {id:'explore',icon:'⌖',label:'探索地点'}, {id:'saved',icon:'▤',label:'已保存行程'}, {id:'budget',icon:'◫',label:'预算与约束'}] as const
const title = computed(() => ({plan:'让下一段旅程，从容出发', explore:'寻找旅程中的下一站', saved:'留住每一次出发的计划', budget:'看清预算，也看清未知'}[tab.value]))
function report(e: unknown) { error.value = e instanceof Error ? e.message : '请求失败，请稍后重试' }
function eventTime(value?:string) { return value ? new Date(value).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '时间未提供' }
function sourceTime(value?:string) { return value ? new Date(value).toLocaleString('zh-CN') : '时间未提供' }
function mergeEvents(items: TravelEvent[]) { events.value = [...new Map([...events.value,...items].map(e=>[e.id,e])).values()].sort((a,b)=>a.id-b.id) }
async function refreshSaved() { saved.value = (await api.itineraries()).items }
async function follow(created: Task) {
  stream?.close(); controller?.abort()
  task.value = created; events.value = []; notice.value = ''; error.value = ''; busy.value = true
  session.taskId = created.id; writeSession(session)
  const localController = new AbortController(); controller = localController
  const localStream = new EventSource(`${apiBase}/tasks/${created.id}/events/stream`); stream = localStream
  localStream.addEventListener('progress', event => { try { mergeEvents([JSON.parse((event as MessageEvent).data)]) } catch {} })
  localStream.addEventListener('terminal', () => localStream.close())
  localStream.onerror = () => localStream.close() // Polling continues independently.
  try {
    const final = await api.wait(created.id, (value, items)=>{ task.value=value; mergeEvents(items) }, {signal:localController.signal})
    task.value = final
    if (final.status === 'succeeded' && final.kind==='draft' && final.draft_id) {
      draft.value=await api.draft(final.draft_id);session.draftId=draft.value.id;writeSession(session)
      draftConflict.value=false
      notice.value='需求草案已生成，请核对后填入表单'
    } else if (final.status === 'succeeded' && final.itinerary_id) {
      itinerary.value = await api.itinerary(final.itinerary_id); selectedDay.value = 0; editing.value = false
      notice.value = '行程已生成并保存'; await refreshSaved()
    } else if (final.error) error.value = final.error.message
    else notice.value = '任务已取消'
  } catch (e) { if (!localController.signal.aborted) report(e) }
  finally { localStream.close(); if(controller===localController) busy.value = false }
}
async function resume() {
  if (!task.value || busy.value) return
  try { await follow(await api.task(task.value.id)) } catch(e) { report(e) }
}
async function generate() {
  if (busy.value || active.value) return
  busy.value = true; error.value = ''; editing.value = false
  const budget = typeof form.budget === 'number' && Number.isFinite(form.budget) ? form.budget : null
  try { await follow(await api.create({...form, budget, user_prices:{}})) } catch(e) { report(e); busy.value=false }
}
async function parseDescription(text:string) {
  if(busy.value||active.value) return
  busy.value=true;error.value=''
  try {await follow(await api.createDraft({text,reference_date:localDate}))} catch(e) {report(e);busy.value=false}
}
async function clarifyDraft(request:Schema<'DraftClarificationRequest'>) {
  if(!draft.value||busy.value||active.value) return
  busy.value=true;error.value='';notice.value=''
  try {
    draft.value=await api.clarifyDraft(draft.value.id,request);draftConflict.value=false
    notice.value=`第 ${draft.value.revision} 版草案已保存，请重新填入表单并核对；尚未启动规划。`
  } catch(e) {draftConflict.value=e instanceof Error&&'code' in e&&e.code==='draft_revision_conflict';report(e)}
  finally {busy.value=false}
}
async function reloadDraft() {
  if(!draft.value||busy.value||active.value) return
  busy.value=true;error.value=''
  try {draft.value=await api.draft(draft.value.id);draftConflict.value=false;notice.value='已加载最新草案，请重新核对补充字段。'}
  catch(e) {report(e)} finally {busy.value=false}
}
function applyDraft(value:Draft) {
  if(busy.value||active.value) return
  Object.assign(form,draftForm(value));tab.value='plan'
  notice.value='草案已填入表单。未提及的城市、关键词或日期需补全，其他空字段使用表单默认值；请核对后点击开始规划。'
}
async function cancel() { if (!task.value) return; try { task.value = await api.cancel(task.value.id) } catch(e) { report(e) } }
async function search() {
  searching.value=true; error.value=''; results.value=[]
  try { results.value = (await api.search(keyword.value, searchCity.value || form.city)).items } catch(e) { report(e) }
  finally { searching.value=false }
}
async function detail(poi: Poi) {
  loadingDetail.value = true; error.value = ''
  try { selectedPoi.value = await api.detail(poi.id) } catch(e) { report(e) }
  finally { loadingDetail.value = false }
}
function edit() {
  if (!itinerary.value) return
  editIds.value = itinerary.value.days.map(d=>d.stops.map(s=>s.poi.id))
  editStay.value=itinerary.value.request.stay_minutes; optimize.value=false
  for (const key of Object.keys(editPrices)) delete editPrices[key]
  for (const d of itinerary.value.days) for (const stop of d.stops) editPrices[stop.poi.id] = stop.user_cost == null ? '' : String(stop.user_cost)
  editing.value=true
  addDay.value=selectedDay.value
  Object.assign(editConstraints, {start_date:itinerary.value.request.start_date, day_start:itinerary.value.request.day_start, day_end:itinerary.value.request.day_end, mode:itinerary.value.request.mode, budget:itinerary.value.request.budget??null})
  for(const key of Object.keys(editDurations)) delete editDurations[key]
  for(const d of itinerary.value.days) for(const stop of d.stops) editDurations[stop.poi.id]=stop.stay_minutes
}
function editName(id:string) { return itinerary.value?.days.flatMap(d=>d.stops).find(s=>s.poi.id===id)?.poi.name || addedPois[id]?.name || id }
function move(index:number, offset:number) { const ids=editIds.value[selectedDay.value]; const target=index+offset; if(target>=0&&target<ids.length) [ids[index],ids[target]]=[ids[target],ids[index]] }
function transfer(id:string) {
  const target=moveDays[id]
  if(target===undefined || target===selectedDay.value) return
  if(editIds.value[target].length>=4) { error.value='目标日期已有 4 站，请先移除或移动地点'; return }
  editIds.value[selectedDay.value]=editIds.value[selectedDay.value].filter(item=>item!==id)
  editIds.value[target].push(id)
}
function add(poi:Poi) {
  if (!editing.value) { error.value='请先在工作台点击编辑行程'; return }
  if(editIds.value.some(d=>d.includes(poi.id))) { error.value='该地点已在行程中'; return }
  if(editIds.value[addDay.value].length>=4) { error.value='每天最多 4 站'; return }
  addedPois[poi.id]=poi; editDurations[poi.id]=editStay.value
  editIds.value[addDay.value].push(poi.id); notice.value=`已加入第 ${addDay.value+1} 天，保存后重新查询路线`
}
async function saveEdit() {
  if (!itinerary.value || busy.value || active.value) return
  if(editIds.value.some(ids=>!ids.length||ids.length>4)) {error.value='每天须保留 1 至 4 个地点';return}
  if(!editConstraints.start_date||editConstraints.day_end<=editConstraints.day_start) {error.value='请填写日期，每日结束时间须晚于开始时间';return}
  const durations: Record<string,number>={}
  for(const id of editIds.value.flat()) {
    const value=editDurations[id]??editStay.value
    if(!Number.isInteger(value)||value<10||value>360) {error.value='各站停留须为 10 至 360 分钟的整数';return}
    durations[id]=value
  }
  let prices: Record<string,number>
  try {prices=userPrices(editIds.value.flat(),editPrices)} catch(e) {report(e);return}
  busy.value=true; error.value=''
  const budget=typeof editConstraints.budget==='number'&&Number.isFinite(editConstraints.budget)?editConstraints.budget:null
  try { await follow(await api.adjust(itinerary.value.id, {...editConstraints, budget, poi_ids_by_day:editIds.value, user_prices:prices, stay_minutes:editStay.value, stay_minutes_by_poi:durations, optimize_order:optimize.value})) }
  catch(e) { report(e); busy.value=false }
}
async function openTrip(id:string) { if(active.value||busy.value) return; try { itinerary.value=await api.itinerary(id); selectedDay.value=0; tab.value='plan'; editing.value=false; selectedPoi.value=null; error.value=''; task.value=null; events.value=[]; delete session.taskId; writeSession(session) } catch(e) { report(e) } }
watch(form, ()=>{session.form={...form};writeSession(session)}, {deep:true})
watch(itinerary, value=>{session.itineraryId=value?.id;writeSession(session)})
watch(tab, value=>history.replaceState(null,'',`#${value}`))
function hashChanged() {const value=location.hash.slice(1);if(tabs.includes(value as Tab)) tab.value=value as Tab}
onMounted(async()=>{
  window.addEventListener('hashchange',hashChanged)
  restoring.value=true
  try {
    capability.value=await api.capabilities(); await refreshSaved()
    if(typeof session.itineraryId==='string') {
      try { itinerary.value=await api.itinerary(session.itineraryId) } catch {delete session.itineraryId;writeSession(session)}
    }
    if(typeof session.draftId==='string') {
      try {draft.value=await api.draft(session.draftId)} catch {delete session.draftId;writeSession(session)}
    }
    if(typeof session.taskId==='string') {
      try { const existing=await api.task(session.taskId);restoring.value=false;await follow(existing) }
      catch(e) {report(e)}
    }
  } catch(e) {report(e)} finally {restoring.value=false}
})
onBeforeUnmount(()=>{stream?.close(); controller?.abort();window.removeEventListener('hashchange',hashChanged)})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="#" @click.prevent="tab='plan'"><span class="brand-mark">↗</span><span>TravelAgent<small>旅行规划工作台</small></span></a>
      <div class="nav-label">你的旅行空间</div>
      <nav><button v-for="item in nav" :key="item.id" :class="{selected:tab===item.id}" @click="tab=item.id"><span>{{item.icon}}</span>{{item.label}}<span v-if="item.id==='saved'" class="count">{{saved.length}}</span></button></nav>
      <div class="sidebar-bottom"><span class="dot" :class="{offline:!capability?.configured}"/>{{capability?.configured ? '真实数据服务已配置' : '真实数据服务待配置'}}<small>每一个地点，都有来源</small></div>
    </aside>
    <main>
      <header class="topbar"><span>TRAVEL WORKSPACE <span class="separator">/</span> {{nav.find(n=>n.id===tab)?.label}}</span><span class="local-badge">本地旅行空间</span></header>
      <div class="page-heading"><div><div class="eyebrow">PLAN WITH INTENTION</div><h1>{{title}}</h1><p>把地点、路线与时间放在一起，规划属于你的旅程。</p></div><span class="heading-tag">Web 工作台 <span>01</span></span></div>
      <div v-if="error" role="alert" class="alert error"><span>{{error}}</span><button aria-label="关闭错误提示" @click="error=''">×</button></div>
      <div v-if="notice" role="status" class="alert success">{{notice}}</div>
      <div v-if="capability && !capability.configured" class="config-note">高德数据将在授权配置后启用。规划与搜索目前会明确提示数据不可用。</div>

      <div v-if="tab==='plan'" class="workspace">
        <section class="card planner-form">
          <div class="section-heading"><span class="step">01</span><div><h2>这次，去哪里？</h2><p>从几个简单的选择开始</p></div></div>
          <form @submit.prevent="generate">
            <label>目的地<input v-model="form.city" required maxlength="60" placeholder="输入城市，例如杭州" :disabled="busy||active"/></label>
            <label>地点关键词<textarea v-model="form.query" required maxlength="240" rows="3" placeholder="例如：博物馆、公园、咖啡" :disabled="busy||active"/><small>用于真实地点搜索，硬约束请在下方填写</small></label>
            <label>出发日期<input v-model="form.start_date" type="date" required :disabled="busy||active"/></label>
            <div class="field-row"><label>旅行天数<select v-model.number="form.days"><option v-for="n in 3" :value="n">{{n}} 天</option></select></label><label>每天站数<select v-model.number="form.stops_per_day"><option v-for="n in 4" :value="n">{{n}} 站</option></select></label></div>
            <div class="field-row"><label>每日开始<input v-model="form.day_start" type="time" required/></label><label>每日结束<input v-model="form.day_end" type="time" required/></label></div>
            <label>每站停留（分钟）<input v-model.number="form.stay_minutes" type="number" min="10" max="360" required/><small>这是你设定的时间，可在生成后调整</small></label>
            <label>交通方式<select v-model="form.mode"><option value="walking">步行 · 真实步行路线</option><option value="driving">驾车 · 真实驾车路线</option></select></label>
            <label>总预算（可选）<div class="money-input"><span>¥</span><input v-model.number="form.budget" type="number" min="0" placeholder="输入预算上限"/></div></label>
            <button class="primary full" type="submit" :disabled="busy||active">{{busy||active ? (task?.kind==='draft'?'正在整理需求…':'正在规划旅程…') : '开始规划'}}<span>↗</span></button>
          </form>
          <p class="form-footnote">路线与时间由后端算法计算。缺失的费用保留未知。</p>
        </section>
        <div class="workspace-main">
          <RequestAssistant :draft="draft" :capability="capability" :disabled="busy||active" :conflict="draftConflict" @parse="parseDescription" @apply="applyDraft" @clarify="clarifyDraft" @reload="reloadDraft"/>
          <section class="card execution"><div class="section-title"><h2>{{task?.kind==='draft'?'需求整理过程':'规划过程'}} <span v-if="task" class="status-pill" :class="task.status">{{statusLabels[task.status]}}</span></h2><button v-if="active" class="text-button" @click="cancel">取消任务</button></div>
            <div v-if="!task" class="execution-empty"><span>◷</span>提交需求后，在这里查看真实执行进度。</div>
            <ol v-else class="event-list"><li v-for="event in events" :key="event.id"><span class="event-dot"/><span>{{event.message}}</span><time>{{eventTime(event.timestamp)}}</time></li></ol>
            <div v-if="task" class="task-controls"><small class="task-id">任务 {{task.id}}</small><button v-if="!busy" class="text-button" @click="resume">重新查询状态 ↻</button></div>
            <small v-if="restoring" role="status">正在恢复上次的工作空间…</small>
          </section>
          <section class="card route-workspace">
            <div class="section-title"><div><div class="eyebrow">YOUR ITINERARY</div><h2>{{itinerary?.title || '旅程地图与时间轴'}}</h2></div><button v-if="itinerary && !editing" class="secondary" :disabled="active||busy" @click="edit">编辑行程</button></div>
            <div v-if="itinerary" class="day-tabs"><button v-for="(d,i) in itinerary.days" :class="{selected:selectedDay===i}" @click="selectedDay=i">DAY {{i+1}}<small>{{d.date}}</small></button></div>
            <div v-if="day" class="day-summary"><span>{{day.stops.length}} 站</span><span>停留 {{day.stops.reduce((sum,s)=>sum+s.stay_minutes,0)}} 分钟</span><span>交通 {{day.stops.reduce((sum,s)=>sum+(s.travel_to_next?.duration_min??0),0)}} 分钟</span><span>{{day.stops.reduce((sum,s)=>sum+(s.travel_to_next?.distance_km??0),0).toFixed(2)}} km</span><small v-if="editing">当前地图与汇总为已保存版本，重算后更新</small></div>
            <div class="route-columns">
              <div class="timeline">
                <div v-if="!itinerary" class="empty-state"><span>↗</span><h3>你的旅程，等待出发</h3><p>选择目的地并开始规划，地点和每日行程会在这里展开。</p></div>
                <template v-else-if="editing">
                  <div class="edit-note">跨天移动地点、逐站调整时间与费用。保存时查询真实路线，并保留原版本。</div>
                  <fieldset class="edit-fields" :disabled="busy||active">
                  <div v-for="(id,i) in editIds[selectedDay]" :key="id" class="edit-stop"><strong>{{i+1}}. {{editName(id)}}</strong><div class="edit-actions"><button :disabled="i===0" :aria-label="`上移 ${editName(id)}`" @click="move(i,-1)">↑</button><button :disabled="i===editIds[selectedDay].length-1" :aria-label="`下移 ${editName(id)}`" @click="move(i,1)">↓</button><button @click="editIds[selectedDay].splice(i,1)">移除</button></div><div class="field-row"><label>停留（分钟）<input v-model.number="editDurations[id]" type="number" min="10" max="360"/></label><label>用户录入费用<input v-model="editPrices[id]" type="number" min="0" placeholder="未知"/></label></div><div v-if="editIds.length>1" class="transfer-row"><select v-model.number="moveDays[id]" :aria-label="`移动 ${editName(id)} 到哪一天`"><option :value="undefined" disabled>选择目标日</option><option v-for="(_,index) in editIds" :value="index" :disabled="index===selectedDay">第 {{index+1}} 天</option></select><button class="text-button" @click="transfer(id)">移动</button></div></div>
                  <p v-if="!editIds[selectedDay].length" class="edit-note">此日尚无地点，请从其他日期移动或搜索添加。</p>
                  <details class="edit-constraints" open><summary>日期与行程约束</summary><label>出发日期<input v-model="editConstraints.start_date" type="date" required/></label><div class="field-row"><label>每日开始<input v-model="editConstraints.day_start" type="time" required/></label><label>每日结束<input v-model="editConstraints.day_end" type="time" required/></label></div><label>交通方式<select v-model="editConstraints.mode"><option value="walking">步行</option><option value="driving">驾车</option></select></label><label>总预算上限<input v-model.number="editConstraints.budget" type="number" min="0" placeholder="留空取消上限"/></label><label>新增站点默认停留（分钟）<input v-model.number="editStay" type="number" min="10" max="360"/></label></details><label class="check-label"><input v-model="optimize" type="checkbox"/>按真实距离重新排序</label>
                  </fieldset>
                  <div class="edit-actions"><button class="primary" :disabled="busy||active" @click="saveEdit">保存并重算</button><button class="secondary" :disabled="busy||active" @click="editing=false">退出编辑</button></div><button class="text-button" @click="tab='explore';searchCity=itinerary.request.city">探索并添加地点 ↗</button>
                </template>
                <template v-else><article v-for="(stop,i) in day?.stops" :key="stop.poi.id" class="timeline-stop"><div class="stop-number">{{String(i+1).padStart(2,'0')}}</div><div class="stop-body"><div class="stop-time">{{stop.arrival_time}} <span>— {{stop.departure_time}}</span></div><button class="poi-name" @click="detail(stop.poi)">{{stop.poi.name}}</button><p>{{stop.poi.address || '地址未提供'}}</p><div class="stop-meta"><span>{{stop.stay_minutes}} 分钟 · 用户设定</span><span>{{stop.user_cost==null?'费用未知':`¥${stop.user_cost}`}}</span></div></div><div v-if="stop.travel_to_next" class="travel-leg">↳ {{stop.travel_to_next.mode==='walking'?'步行':'驾车'}} {{stop.travel_to_next.duration_min}} 分钟 · {{stop.travel_to_next.distance_km.toFixed(2)}} km <small>高德路线</small></div></article></template>
              </div>
              <RouteMap :itinerary="itinerary" :selected-day="selectedDay" :poi="selectedPoi"/>
            </div>
          </section>
        </div>
      </div>

      <section v-if="tab==='explore'" class="explore-layout">
        <div class="card"><div class="section-title"><h2>探索真实地点</h2><span class="subtle">来源 · 高德地图</span></div><form class="search-form" @submit.prevent="search"><input v-model="searchCity" :placeholder="form.city||'城市'" required aria-label="搜索城市"/><input v-model="keyword" placeholder="输入地点名称或类别" required aria-label="搜索关键词"/><button class="primary" :disabled="searching">{{searching?'搜索中…':'搜索'}}</button></form>
          <div v-if="editing" class="add-target">加入 <select v-model.number="addDay"><option v-for="(_,i) in editIds" :value="i">第 {{i+1}} 天</option></select><button class="text-button" @click="tab='plan'">返回编辑</button></div>
          <div v-if="!results.length" class="empty-state"><span>⌖</span><h3>{{searching?'正在查找地点':'从一个关键词开始探索'}}</h3><p>搜索结果与详情来自授权接口，缺失信息会明确标记。</p></div>
          <article v-for="poi in results" :key="poi.id" class="poi-card"><div><span class="poi-category">{{poi.category || '类别未提供'}}</span><button class="poi-name" @click="detail(poi)">{{poi.name}}</button><p>{{poi.address || '地址未提供'}}</p><small>评分 {{poi.rating ?? '未知'}} · 人均消费 {{poi.average_spend==null?'未知':`¥${poi.average_spend}（非门票）`}}</small></div><button v-if="editing" class="secondary" @click="add(poi)">＋ 加入行程</button></article>
        </div><RouteMap :itinerary="itinerary" :selected-day="selectedDay" :poi="selectedPoi"/>
      </section>

      <section v-if="tab==='saved'" class="card saved-panel"><div class="section-title"><h2>已保存行程</h2><button class="text-button" @click="refreshSaved().catch(report)">刷新 ↻</button></div><div v-if="!saved.length" class="empty-state"><span>▤</span><h3>这里将收藏你的旅程</h3><p>成功生成的行程会自动保存；重新调整后保留原版本。</p></div><div class="saved-grid"><button v-for="trip in saved" :key="trip.id" class="saved-card" :disabled="active||busy" @click="openTrip(trip.id)"><span class="eyebrow">{{trip.parent_id?'ADJUSTED ITINERARY':'SAVED ITINERARY'}}</span><h3>{{trip.title}}</h3><p>{{trip.request.start_date}} · {{trip.days.length}} 天</p><div><span>{{trip.days.reduce((n,d)=>n+d.stops.length,0)}} 个地点</span><span>打开行程 ↗</span></div></button></div></section>

      <section v-if="tab==='budget'" class="budget-layout"><div class="card"><div class="section-title"><h2>预算与约束</h2><span class="subtle">{{itinerary?.title || '尚未选择行程'}}</span></div><div v-if="!itinerary" class="empty-state"><span>◫</span><h3>先规划，再核对</h3><p>生成行程后查看已知费用、未知费用与约束结果。</p></div><template v-else><div class="budget-stats"><div><small>已知费用小计</small><strong>¥{{itinerary.budget.known_subtotal}}</strong><span>仅汇总用户录入的站点费用</span></div><div><small>总预算上限</small><strong>{{itinerary.budget.limit==null?'未设置':`¥${itinerary.budget.limit}`}}</strong><span>{{itinerary.budget.status==='exceeded'?'已知费用已超预算':'总额未知，无法确认预算满足'}}</span></div></div><h3>仍需补全的费用</h3><ul class="warning-list"><li v-for="item in itinerary.budget.unknown_items">{{item}}</li></ul><h3>行程约束与提醒</h3><ul class="warning-list"><li v-for="warning in itinerary.warnings">{{warning}}</li></ul><button class="secondary" @click="tab='plan';edit()" :disabled="active||busy">录入费用与调整行程</button></template></div><aside class="card capability-card"><div class="eyebrow">DATA COVERAGE</div><h2>数据覆盖范围</h2><ul class="warning-list"><li v-for="item in capability?.limitations">{{item}}</li></ul><p>空值表示来源未提供；不会自动补成免费、零交通时间或模拟评论。</p></aside></section>

      <div v-if="selectedPoi" class="modal-backdrop" @click.self="selectedPoi=null"><section class="poi-dialog" role="dialog" aria-modal="true" aria-label="地点详情"><button class="dialog-close" aria-label="关闭地点详情" @click="selectedPoi=null">×</button><div class="eyebrow">POI DETAILS · AMAP</div><h2>{{selectedPoi.name}}</h2><p>{{selectedPoi.address || '地址未知'}}</p><dl><dt>类别</dt><dd>{{selectedPoi.category || '未知'}}</dd><dt>评分</dt><dd>{{selectedPoi.rating ?? '未知'}}</dd><dt>人均消费（非门票）</dt><dd>{{selectedPoi.average_spend==null?'未知':`¥${selectedPoi.average_spend}`}}</dd><dt>营业时间</dt><dd>{{selectedPoi.opening_hours || '未知，需人工确认'}}</dd><dt>坐标</dt><dd>{{selectedPoi.longitude}}, {{selectedPoi.latitude}} · GCJ-02</dd><dt>来源获取时间</dt><dd>{{sourceTime(selectedPoi.source.retrieved_at)}}</dd></dl><p class="detail-note">尚无授权评论和票价数据。人均消费不能作为门票或最终预算。</p><button v-if="editing" class="primary" @click="add(selectedPoi);selectedPoi=null">加入第 {{addDay+1}} 天</button></section></div>
      <div v-if="loadingDetail" class="loading-toast" role="status">正在获取真实地点详情…</div>
      <footer>TravelAgent <span>·</span> 地点有来源，规划有依据 <span class="footer-right">{{new Date().getFullYear()}} / YOUR NEXT JOURNEY</span></footer>
    </main>
  </div>
</template>

