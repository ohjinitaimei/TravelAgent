<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { scheduleAt, sharedScheduleReady, type ScheduleInput, type ScheduleOptions } from '../schedules'

const props=defineProps<{value:ScheduleOptions;days:number;disabled?:boolean;editing?:boolean}>()
const emit=defineEmits<{change:[value:ScheduleOptions];apply:[day:number]}>()
const modeError=ref('')
const individual=computed(()=>props.value.day_schedules!=null)
const raw=(event:Event)=>(event.target as HTMLInputElement).value
const number=(event:Event)=>raw(event)===''?'':Number(raw(event))
function mode(event:Event){
  const control=event.target as HTMLInputElement
  if(control.checked&&!sharedScheduleReady(props.value)){
    control.checked=false;modeError.value='请先完整填写共用时段和默认停留，再开启逐日设置。';return
  }
  modeError.value=''
  if(control.checked){
    const shared=scheduleAt(props.value,0)??{day_start:'09:00',day_end:'18:00',stay_minutes:60}
    emit('change',{day_schedules:Array.from({length:props.days},()=>({...shared}))})
  }else{
    const first=props.value.day_schedules?.[0]
    emit('change',{...first,day_schedules:null})
  }
}
function changeDay(index:number,key:keyof ScheduleInput,value:string|number){
  const days=props.value.day_schedules?.map(day=>({...day}))
  if(!days?.[index])return
  if(key==='stay_minutes')days[index].stay_minutes=value
  else days[index][key]=String(value)
  emit('change',{day_schedules:days})
}
watch(()=>props.days,count=>{
  if(props.value.day_schedules)emit('change',{day_schedules:Array.from({length:count},(_,index)=>({... (props.value.day_schedules?.[index]??{day_start:props.value.day_start??'09:00',day_end:props.value.day_end??'18:00',stay_minutes:props.value.stay_minutes??60})}))})
})
</script>

<template>
  <div class="journey-schedule">
    <label class="check-label"><input type="checkbox" :checked="individual" :disabled="disabled" @change="mode"/>按天设置时段与默认停留</label>
    <p v-if="modeError" role="alert">{{modeError}}</p>
    <template v-if="!individual">
      <div class="field-row"><label>每日开始<input :value="value.day_start" name="day_start" type="time" required :disabled="disabled" @input="emit('change',{day_start:raw($event)})"/></label><label>每日结束<input :value="value.day_end" name="day_end" data-after="day_start" type="time" required :disabled="disabled" @input="emit('change',{day_end:raw($event)})"/></label></div>
      <label>{{editing?'新增站点默认停留（分钟）':'每站停留（分钟）'}}<input :value="value.stay_minutes" name="stay_minutes" type="number" min="10" max="360" step="1" required :disabled="disabled" @input="emit('change',{stay_minutes:number($event)})"/><small>{{editing?'已排站点保留当前停留，可逐站修改。':'这是你设定的时间，可在生成后调整'}}</small></label>
    </template>
    <fieldset v-else class="daily-schedules" aria-label="逐日时段与默认停留" :disabled="disabled">
      <legend>逐日时段与默认停留</legend>
      <p>每天独立核验，不支持跨夜；切回共用采用第 1 天设置。新增日期复制共用默认，减少天数仅保留对应日期。</p>
      <section v-for="(day,index) in value.day_schedules" :key="index" :data-schedule-day="index" :aria-label="`第 ${index+1} 天时段`">
        <h3>第 {{index+1}} 天</h3>
        <div class="field-row"><label>第 {{index+1}} 天开始<input :value="day.day_start" :name="`day_start_${index}`" type="time" required @input="changeDay(index,'day_start',raw($event))"/></label><label>第 {{index+1}} 天结束<input :value="day.day_end" :name="`day_end_${index}`" :data-after="`day_start_${index}`" type="time" required @input="changeDay(index,'day_end',raw($event))"/></label></div>
        <label>第 {{index+1}} 天默认停留（分钟）<input :value="day.stay_minutes" :name="`day_stay_${index}`" type="number" min="10" max="360" step="1" required @input="changeDay(index,'stay_minutes',number($event))"/></label>
        <button v-if="editing" type="button" class="secondary" @click="emit('apply',index)">应用到第 {{index+1}} 天站点</button>
      </section>
      <p>{{editing?'修改默认不会覆盖已有逐站停留。点击“应用到本日站点”对应按钮才会批量修改，跨日移动仍保留站点当前停留。':'逐站用户设置优先于当日默认。'}} 时段和停留来自用户输入，不代表营业或预约时间。</p>
    </fieldset>
  </div>
</template>

<style scoped>
.journey-schedule{grid-column:1/-1;min-width:0}.journey-schedule label{display:block;margin:10px 0}.journey-schedule input{width:100%;box-sizing:border-box}.journey-schedule .check-label{display:flex}.journey-schedule .check-label input{width:auto}.daily-schedules{min-width:0;border:1px solid var(--line);border-radius:10px;padding:12px;margin:12px 0}.daily-schedules legend,.daily-schedules h3{font-size:12px;color:var(--green)}.daily-schedules p,.journey-schedule small{font-size:11px;line-height:1.7;color:var(--muted)}.daily-schedules section+section{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}
</style>
