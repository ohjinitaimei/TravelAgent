<script setup lang="ts">
import { computed, watch } from 'vue'
import EndpointPicker from './EndpointPicker.vue'
import type { Poi } from '../api'
import { endpointAt, type EndpointOptions, type DayEndpoints } from '../endpoints'

const props=defineProps<{value:EndpointOptions;days:number;city:string;disabled?:boolean;knownPoi:(id?:string|null)=>Poi|null|undefined}>()
const emit=defineEmits<{change:[value:EndpointOptions];loaded:[poi:Poi]}>()
const individual=computed(()=>props.value.day_endpoints!=null)
function mode(event:Event) {
  if((event.target as HTMLInputElement).checked) {
    const shared=endpointAt(props.value,0)??{}
    emit('change',{day_origin_poi_id:null,day_destination_poi_id:null,day_endpoints:Array.from({length:props.days},()=>({...shared}))})
  } else {
    const first=props.value.day_endpoints?.[0]
    emit('change',{day_origin_poi_id:first?.origin_poi_id??null,day_destination_poi_id:first?.destination_poi_id??null,day_endpoints:null})
  }
}
function changeDay(index:number,key:keyof DayEndpoints,value:string|null) {
  const days=props.value.day_endpoints?.map(day=>({...day}))
  if(days?.[index]){days[index][key]=value;emit('change',{day_endpoints:days})}
}
watch(()=>props.days,count=>{
  if(props.value.day_endpoints)emit('change',{day_endpoints:Array.from({length:count},(_,index)=>({...props.value.day_endpoints?.[index]}))})
})
</script>

<template>
  <div class="journey-endpoints">
    <label class="check-label"><input type="checkbox" :checked="individual" :disabled="disabled" @change="mode"/>按天设置出发和返回</label>
    <p class="subtle">开始时间为离开当天出发地，结束时间包含抵达当天返回地；空侧不计往返。每天独立选择，不推断跨夜接驳。</p>
    <template v-if="!individual">
      <p class="subtle">所有日期共用所选起终点。</p>
      <EndpointPicker :model-value="value.day_origin_poi_id" :known-poi="knownPoi(value.day_origin_poi_id)" label="出发地" :city="city" :disabled="disabled" @loaded="emit('loaded',$event)" @update:model-value="emit('change',{day_origin_poi_id:$event})"/>
      <EndpointPicker :model-value="value.day_destination_poi_id" :known-poi="knownPoi(value.day_destination_poi_id)" label="返回地" :city="city" :disabled="disabled" @loaded="emit('loaded',$event)" @update:model-value="emit('change',{day_destination_poi_id:$event})"/>
    </template>
    <fieldset v-else class="daily-endpoints" aria-label="逐日起终点" :disabled="disabled">
      <legend>逐日起终点</legend>
      <p class="subtle">切回共用将使用第 1 天选择。减少天数仅保留对应日期的设置；新增日期留空。</p>
      <section v-for="(day,index) in value.day_endpoints" :key="index" :aria-label="`第 ${index+1} 天起终点`">
        <h3>第 {{index+1}} 天</h3>
        <EndpointPicker :model-value="day.origin_poi_id" :known-poi="knownPoi(day.origin_poi_id)" :label="`第 ${index+1} 天出发地`" :city="city" :disabled="disabled" @loaded="emit('loaded',$event)" @update:model-value="changeDay(index,'origin_poi_id',$event)"/>
        <EndpointPicker :model-value="day.destination_poi_id" :known-poi="knownPoi(day.destination_poi_id)" :label="`第 ${index+1} 天返回地`" :city="city" :disabled="disabled" @loaded="emit('loaded',$event)" @update:model-value="changeDay(index,'destination_poi_id',$event)"/>
      </section>
    </fieldset>
  </div>
</template>

<style scoped>
.daily-endpoints{min-width:0;border:1px solid var(--line);border-radius:10px;padding:12px;margin:12px 0}.daily-endpoints legend,.daily-endpoints h3{font-size:12px;color:var(--green)}.daily-endpoints section+section{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}.daily-endpoints h3{margin:6px 0}
</style>
