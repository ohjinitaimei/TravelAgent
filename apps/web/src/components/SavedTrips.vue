<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { useTravelApi, type Itinerary } from '../api'
import { shortVersion, versionChanges, versionTime, type VersionFilter } from '../versions'
import VersionComparison from './VersionComparison.vue'
const props=defineProps<{trips:Itinerary[];disabled:boolean}>()
const emit=defineEmits<{updated:[value:{items:Itinerary[];total?:number|null}];open:[id:string,event:MouseEvent]}>()
const api=useTravelApi()
const filter=reactive<VersionFilter>({query:'',kind:'all',order:'newest',parentId:null})
const visible=shallowRef<Itinerary[]>(props.trips),total=ref<number|null>(null)
const counts=shallowRef<Record<string,number>>({}),fetching=ref(true),listError=ref('')
const nextCursor=ref<string|null>(null),cursors=ref<string[]>([]),pageIndex=ref(0)
let listGeneration=0,listController:AbortController|undefined,filterTimer:ReturnType<typeof setTimeout>|undefined
let retryList=()=>{}
async function loadList(cursor?:string,index=0,reset=false) {
  const token=++listGeneration
  listController?.abort();listController=new AbortController()
  fetching.value=true;listError.value=''
  if(reset){visible.value=[];total.value=null;counts.value={};nextCursor.value=null;cursors.value=[];pageIndex.value=0}
  retryList=()=>{void loadList(cursor,index,reset)}
  try {
    const result=await api.itineraries({limit:50,query:filter.query.trim(),kind:filter.kind,order:filter.order,parent_id:filter.parentId,cursor},listController.signal)
    if(token!==listGeneration)return
    visible.value=result.items;total.value=result.total??null;counts.value=result.direct_adjustment_counts??{}
    nextCursor.value=result.next_cursor??null;pageIndex.value=index
    cursors.value=[...cursors.value.slice(0,index),result.page_cursor??'']
    if(index===0&&!filter.query.trim()&&filter.kind==='all'&&!filter.parentId)emit('updated',result)
  } catch {
    if(token===listGeneration)listError.value='列表读取失败。可重试本次读取，或点击刷新重新开始；当前行程与编辑草稿已保留。'
  } finally {if(token===listGeneration)fetching.value=false}
}
function refreshList(){if(props.disabled)return;clearTimeout(filterTimer);void loadList(undefined,0,true)}
watch(()=>[filter.query,filter.kind,filter.order,filter.parentId],()=>{
  // Invalidate immediately, including the debounce interval. Older reads cannot overwrite new input.
  listGeneration++;listController?.abort();clearTimeout(filterTimer)
  visible.value=[];total.value=null;counts.value={};nextCursor.value=null;listError.value='';fetching.value=true
  filterTimer=setTimeout(()=>{void loadList(undefined,0,true)},250)
})
onMounted(()=>{void loadList()})
const comparison=shallowRef<{parent:Itinerary;child:Itinerary}|null>(null)
const comparisonId=ref<string|null>(null),comparisonError=ref(''),comparing=ref(false)
const heading=ref<HTMLElement>(),comparisonHeading=ref<HTMLElement>()
let generation=0,opener:HTMLElement|null=null
function clearFilters(){filter.query='';filter.kind='all';filter.parentId=null}
function related(id:string){clearFilters();filter.parentId=id}
async function closeComparison(){
  const token=++generation
  comparison.value=null;comparisonId.value=null;comparisonError.value='';comparing.value=false
  // Wait for Vue to re-enable the opener before restoring keyboard focus.
  await nextTick()
  if(token!==generation)return
  if(opener?.isConnected&&!(opener instanceof HTMLButtonElement&&opener.disabled))opener.focus();else heading.value?.focus()
}
async function compare(id:string,event?:MouseEvent) {
  if(props.disabled)return
  const token=++generation
  if(event?.currentTarget instanceof HTMLElement)opener=event.currentTarget
  comparisonId.value=id;comparison.value=null;comparisonError.value='';comparing.value=true
  await nextTick();comparisonHeading.value?.focus()
  try {
    const child=await api.itinerary(id)
    if(token!==generation)return
    if(child.id!==id||!child.parent_id)throw new Error('该版本没有可读取的来源，未生成对照。')
    const parent=await api.itinerary(child.parent_id)
    if(token!==generation)return
    versionChanges(parent,child) // Reject mismatched responses before displaying either version.
    comparison.value={parent,child}
  } catch {
    if(token===generation)comparisonError.value='版本对照暂不可用，请检查连接及来源版本的访问权限后重试。'
  } finally {if(token===generation)comparing.value=false}
}
onBeforeUnmount(()=>{generation++;listGeneration++;clearTimeout(filterTimer);listController?.abort()})
</script>

<template>
  <section class="card saved-panel">
    <div class="section-title"><h2 ref="heading" tabindex="-1">已保存行程</h2><button class="text-button" :disabled="disabled||fetching" @click="refreshList">刷新 ↻</button></div>
      <fieldset class="version-filters" :disabled="disabled"><legend class="sr-only">筛选已保存版本</legend><label>搜索已保存行程<input v-model="filter.query" type="search" maxlength="120" placeholder="标题、城市、出发日期或版本标识"/></label><label>版本类型<select v-model="filter.kind"><option value="all">全部版本</option><option value="original">原行程</option><option value="adjusted">调整版本</option></select></label><label>行程排序<select v-model="filter.order"><option value="newest">最近保存</option><option value="oldest">最早保存</option><option value="departure">出发日期</option></select></label><button type="button" class="text-button" @click="clearFilters">清除筛选</button></fieldset>
      <p class="version-scope" role="status"><template v-if="fetching">正在查询已保存版本…</template><template v-else><template v-if="total!==null">当前账号全库匹配 {{total}} 个版本 · </template><template v-else>服务未提供总数 · </template>第 {{pageIndex+1}} 页，本页 {{visible.length}} 个。每页最多 50 个；翻页沿用查询快照，刷新纳入新记录。</template></p>
      <div v-if="listError" role="alert"><p>{{listError}}</p><button class="secondary" :disabled="disabled||fetching" @click="retryList">重试列表读取</button></div>
      <div v-if="filter.parentId" class="version-scope relation-filter">正在查看 #{{shortVersion(filter.parentId)}} 的直接调整版本（当前账号全库查询）。<button class="text-button" @click="filter.parentId=null">取消关系筛选</button></div>
      <div v-if="!fetching&&!listError&&!visible.length" class="empty-state"><template v-if="!filter.query.trim()&&filter.kind==='all'&&!filter.parentId"><span>▤</span><h3>这里将收藏你的旅程</h3><p>成功生成的行程会自动保存；重新调整后保留原版本。</p></template><template v-else><h3>没有匹配的版本</h3><button class="secondary" @click="clearFilters">显示全部版本</button></template></div>
      <div class="saved-grid"><article v-for="trip in visible" :key="trip.id" class="version-item" :data-version-id="trip.id">
        <button class="saved-card" :data-trip-id="trip.id" :disabled="disabled||fetching" @click="emit('open',trip.id,$event)"><span class="eyebrow">{{trip.parent_id?'ADJUSTED ITINERARY':'SAVED ITINERARY'}}</span><h3>{{trip.title}}</h3><p>{{trip.request.start_date}} · {{trip.days.length}} 天</p><p class="version-identity"><strong>{{trip.parent_id?'调整版本':'原行程'}}</strong> <code :title="trip.id">#{{shortVersion(trip.id)}}</code></p><p class="version-saved-time">保存于 {{versionTime(trip.created_at)}}</p><div><span>{{trip.days.reduce((n,d)=>n+d.stops.length,0)}} 个地点</span><span>打开行程 ↗</span></div></button>
        <div class="version-links"><template v-if="trip.parent_id"><p :title="trip.parent_id">来源 #{{shortVersion(trip.parent_id)}} <small v-if="!visible.some(item=>item.id===trip.parent_id)">未在当前列表中</small></p><button class="text-button" :disabled="disabled||fetching" @click="emit('open',trip.parent_id,$event)">打开来源版本</button><button class="secondary" :disabled="disabled||comparing||fetching" @click="compare(trip.id,$event)">对比来源版本</button></template><p>查询快照内 {{counts[trip.id]??'数量未提供'}} 个直接调整版本</p><button v-if="(counts[trip.id]??0)>0" class="text-button" :disabled="disabled||fetching" @click="related(trip.id)">查看直接调整版本</button></div>
      </article></div>
      <nav class="version-pagination" aria-label="已保存行程分页"><button class="secondary" :disabled="disabled||fetching||pageIndex===0||!cursors[pageIndex-1]" @click="loadList(cursors[pageIndex-1],pageIndex-1)">上一页</button><span>第 {{pageIndex+1}} 页</span><button class="secondary" :disabled="disabled||fetching||!nextCursor" @click="loadList(nextCursor??undefined,pageIndex+1)">下一页</button></nav>
    <section v-if="comparisonId" class="saved-comparison" aria-label="已保存版本对照"><div class="comparison-heading"><h3 ref="comparisonHeading" tabindex="-1">调整前后对照</h3><button class="text-button" aria-label="关闭版本对照" @click="closeComparison">关闭</button></div><p v-if="comparing" role="status">正在读取两个已保存版本…</p><div v-else-if="comparisonError" role="alert"><p>{{comparisonError}}</p><button class="secondary" :disabled="disabled" @click="compare(comparisonId)">重试版本对照</button></div><template v-else-if="comparison"><VersionComparison :parent="comparison.parent" :child="comparison.child"/><div class="comparison-actions"><button class="secondary" :disabled="disabled" @click="emit('open',comparison.parent.id,$event)">打开对照中的来源版本</button><button class="secondary" :disabled="disabled" @click="emit('open',comparison.child.id,$event)">打开对照中的调整版本</button></div></template></section>
  </section>
</template>

<style scoped>
.version-pagination{display:flex;justify-content:center;align-items:center;gap:16px;flex-wrap:wrap;margin-top:22px;font-size:12px}
.version-filters{display:flex;gap:14px;flex-wrap:wrap;align-items:end;border:0;padding:0;margin:8px 0 14px;min-width:0}.version-filters label{display:flex;flex-direction:column;gap:7px;font-size:12px}.version-filters label:first-of-type{flex:1 1 260px}.version-filters input,.version-filters select{font:inherit;border:1px solid var(--line);border-radius:7px;padding:10px;background:white;color:inherit;min-width:0}.version-filters .text-button{padding:10px 0}.version-scope{color:var(--muted);font-size:12px;line-height:1.8;margin:8px 0 18px}.relation-filter{background:#edf4e9;padding:12px;border-radius:8px}.relation-filter button{margin-left:12px}.version-item{border:1px solid var(--line);border-radius:12px;overflow:hidden;min-width:0}.version-item .saved-card{width:100%;height:auto;border:0;border-radius:0}.version-identity{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.version-identity code{font-size:12px}.version-saved-time{font-size:11px!important;line-height:1.8}.version-links{border-top:1px solid var(--line);padding:14px 20px;display:flex;gap:8px 14px;align-items:center;flex-wrap:wrap;font-size:12px}.version-links p{width:100%;margin:0;overflow-wrap:anywhere}.version-links small{color:var(--muted);margin-left:6px}.saved-comparison{margin-top:24px;border:1px solid var(--line);border-radius:12px;padding:20px;min-width:0}.comparison-heading{display:flex;justify-content:space-between;align-items:center;gap:12px}.comparison-heading h3{font-size:17px}.comparison-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.saved-comparison p{font-size:12px;line-height:1.8;color:var(--muted)}@media(max-width:680px){.version-filters label{flex:1 1 140px}.saved-comparison{padding:14px}.version-links{padding:12px 16px}}
</style>
