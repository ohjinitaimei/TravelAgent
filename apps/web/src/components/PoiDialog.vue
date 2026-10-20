<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { Poi } from '../api'
import { keepDialogFocus } from '../dialogFocus'
const props=defineProps<{poi:Poi|null;editing:boolean;day:number;returnFocus?:HTMLElement|null}>()
const emit=defineEmits<{close:[];add:[poi:Poi]}>()
const dialog=ref<HTMLDialogElement>(),closeButton=ref<HTMLButtonElement>()
let previous:HTMLElement|null=null
function restoreFocus(){if(previous?.isConnected)previous.focus()}
watch(()=>props.poi,async value=>{
  await nextTick()
  if(value&&dialog.value&&!dialog.value.open){previous=props.returnFocus??document.activeElement as HTMLElement;dialog.value.showModal();closeButton.value?.focus()}
  else if(!value&&dialog.value?.open){dialog.value.close();restoreFocus()}
},{immediate:true})
function outside(event:MouseEvent){
  if(event.target!==dialog.value)return
  const rect=dialog.value.getBoundingClientRect()
  if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)emit('close')
}
function sourceTime(value?:string){return value?new Date(value).toLocaleString('zh-CN'):'时间未提供'}
onBeforeUnmount(()=>{dialog.value?.close();restoreFocus()})
</script>

<template>
  <dialog ref="dialog" class="poi-dialog" aria-labelledby="poi-title" aria-describedby="poi-source-note" @cancel.prevent="emit('close')" @click="outside" @keydown="keepDialogFocus">
    <template v-if="poi">
      <button ref="closeButton" autofocus class="dialog-close" aria-label="关闭地点详情" @click="emit('close')">×</button>
      <div class="eyebrow">POI DETAILS · AMAP</div><h2 id="poi-title"><span class="sr-only">地点详情：</span>{{poi.name}}</h2>
      <p>{{poi.address||'地址未知'}}</p>
      <dl><dt>类别</dt><dd>{{poi.category||'未知'}}</dd><dt>评分</dt><dd>{{poi.rating??'未知'}}</dd><dt>人均消费（非门票）</dt><dd>{{poi.average_spend==null?'未知':`¥${poi.average_spend}`}}</dd><dt>营业时间</dt><dd>{{poi.opening_hours||'未知，需人工确认'}}</dd><dt>坐标</dt><dd>{{poi.longitude}}, {{poi.latitude}} · GCJ-02</dd><dt>来源获取时间</dt><dd>{{sourceTime(poi.source.retrieved_at)}}</dd></dl>
      <p id="poi-source-note" class="detail-note">尚无授权评论和票价数据。人均消费不能作为门票或最终预算。</p>
      <button v-if="editing" class="primary" @click="emit('add',poi);emit('close')">加入第 {{day+1}} 天</button>
    </template>
  </dialog>
</template>
