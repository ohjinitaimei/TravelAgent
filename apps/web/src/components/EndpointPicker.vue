<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useTravelApi, type Poi } from '../api'
import { TravelApiError } from '../../../../packages/api-schema/client'

const props=defineProps<{label:string;city:string;modelValue?:string|null;disabled?:boolean;knownPoi?:Poi|null}>()
const emit=defineEmits<{'update:modelValue':[value:string|null];loaded:[poi:Poi]}>()
const api=useTravelApi(),query=ref(''),results=ref<Poi[]>([]),selected=ref<Poi|null>(null)
const issue=ref(''),loading=ref(false),lookingUp=ref(false)
let searchGeneration=0,detailGeneration=0,searchController:AbortController|null=null,detailController:AbortController|null=null
function failureMessage(error:unknown,fallback:string) {
  const message=error instanceof Error?error.message:fallback
  return error instanceof TravelApiError&&error.retryAfterSeconds
    ?`${message}；服务建议等待约 ${error.retryAfterSeconds} 秒后手动重试`:message
}
function choose(poi:Poi) {selected.value=poi;issue.value='';emit('loaded',poi);emit('update:modelValue',poi.id);results.value=[]}
async function search() {
  if(props.disabled||!query.value.trim()||!props.city.trim())return
  const generation=++searchGeneration
  searchController?.abort();searchController=new AbortController()
  loading.value=true;issue.value='';results.value=[]
  try {const value=await api.search(query.value.trim(),props.city,searchController.signal);if(generation===searchGeneration)results.value=value.items}
  catch(error) {if(generation===searchGeneration)issue.value=failureMessage(error,'地点查询失败')}
  finally {if(generation===searchGeneration)loading.value=false}
}
watch(()=>[props.modelValue,props.knownPoi] as const,async ([id,known])=>{
  const generation=++detailGeneration
  detailController?.abort();detailController=null;lookingUp.value=false
  issue.value=''
  if(!id){selected.value=null;return}
  if(known?.id===id){selected.value=known;return}
  if(selected.value?.id===id)return
  selected.value=null;lookingUp.value=true;detailController=new AbortController()
  try {
    const poi=await api.detail(id,detailController.signal)
    if(generation===detailGeneration){if(poi.id!==id)throw Error('地点详情与选择不一致');selected.value=poi;emit('loaded',poi)}
  } catch(error) {if(generation===detailGeneration)issue.value=failureMessage(error,'地点详情读取失败')}
  finally {if(generation===detailGeneration)lookingUp.value=false}
},{immediate:true})
watch(()=>props.city,()=>{searchGeneration++;searchController?.abort();results.value=[];loading.value=false})
onBeforeUnmount(()=>{searchGeneration++;detailGeneration++;searchController?.abort();detailController?.abort()})
</script>

<template>
  <fieldset class="endpoint-picker" :disabled="disabled" :data-endpoint-id="modelValue??undefined" tabindex="-1">
    <legend>{{label}}（可选）</legend>
    <p v-if="modelValue" role="status">已选择：{{selected?.name??`地点 #${modelValue}`}}{{lookingUp?' · 正在核对':''}}</p>
    <p v-else class="subtle">未设置{{label}}</p>
    <button v-if="modelValue" type="button" class="text-button" :aria-label="`清除${label}`" @click="emit('update:modelValue',null)">清除选择</button>
    <label>{{label}}搜索<input v-model="query" maxlength="240" placeholder="按名称搜索真实地点" @keydown.enter.prevent="search"/></label>
    <button type="button" class="secondary" :disabled="loading||!query.trim()||!city.trim()" @click="search">{{loading?'正在查询…':`搜索${label}`}}</button>
    <p v-if="issue" role="alert">{{issue}}；选择仍保留，可重搜或清除。</p>
    <ul v-if="results.length" :aria-label="`${label}搜索结果`"><li v-for="poi in results" :key="poi.id"><button type="button" class="text-button" @click="choose(poi)">选择 {{poi.name}}</button><small>{{poi.address??'地址未提供'}} · {{poi.city??'城市未提供'}}</small></li></ul>
    <p v-else-if="!loading&&query.trim()&&!issue" class="subtle">搜索后从结果中选择，不会根据文字猜测位置。</p>
  </fieldset>
</template>

<style scoped>
.endpoint-picker{border:1px solid var(--line);border-radius:10px;padding:12px;margin:12px 0;min-width:0}.endpoint-picker legend{font-size:12px;color:var(--green);padding:0 5px}.endpoint-picker p,.endpoint-picker small{font-size:11px;line-height:1.7;overflow-wrap:anywhere}.endpoint-picker label{display:block;margin:10px 0}.endpoint-picker input{width:100%;box-sizing:border-box}.endpoint-picker ul{list-style:none;padding:0;max-height:220px;overflow:auto}.endpoint-picker li{padding:8px 0;border-top:1px solid var(--line)}.endpoint-picker small{display:block;color:var(--muted)}
</style>
