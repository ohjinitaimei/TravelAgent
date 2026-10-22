<script setup lang="ts">
import type { DraftDayInput } from '../draft'

const props=defineProps<{value:DraftDayInput[]|null;count:number;selected:boolean;disabled:boolean}>()
const emit=defineEmits<{change:[value:DraftDayInput[]|null];select:[value:boolean]}>()
const blank=():DraftDayInput=>({day_start:'',day_end:'',stay_minutes:null})
function change(index:number,key:keyof DraftDayInput,event:Event) {
  const raw=(event.target as HTMLInputElement).value
  const next=props.value?.map(day=>({...day}))
  if(!next?.[index])return
  if(key==='stay_minutes')next[index].stay_minutes=raw===''?null:Number(raw)
  else next[index][key]=raw
  emit('change',next);emit('select',true)
}
function set(value:DraftDayInput[]|null) {emit('change',value);emit('select',true)}
</script>

<template>
  <fieldset class="draft-daily" aria-label="草案逐日时段与停留" :disabled="disabled">
    <legend>逐日时段与默认停留</legend>
    <p>空白表示用户尚未说明。逐日项数量必须与草案天数一致；修改天数不会自动增删这里的内容。</p>
    <template v-if="value">
      <section v-for="(day,index) in value" :key="index" :aria-label="`草案第 ${index+1} 天时段`">
        <h4>第 {{index+1}} 天</h4>
        <div class="daily-row">
          <label>草案第 {{index+1}} 天开始<input :value="day.day_start" :name="`draft_daily_start_${index}`" :aria-label="`草案第 ${index+1} 天开始`" type="time" :data-skip-validation="!selected" @input="change(index,'day_start',$event)"/></label>
          <label>草案第 {{index+1}} 天结束<input :value="day.day_end" :name="`draft_daily_end_${index}`" :data-after="`draft_daily_start_${index}`" :aria-label="`草案第 ${index+1} 天结束`" type="time" :data-skip-validation="!selected" @input="change(index,'day_end',$event)"/></label>
        </div>
        <label>草案第 {{index+1}} 天默认停留（分钟）<input :value="day.stay_minutes" :aria-label="`草案第 ${index+1} 天默认停留（分钟）`" type="number" min="10" max="360" step="1" placeholder="未说明" :data-skip-validation="!selected" @input="change(index,'stay_minutes',$event)"/></label>
      </section>
      <div class="daily-actions"><button type="button" class="text-button" :disabled="value.length>=3" @click="set([...value.map(day=>({...day})),blank()])">新增一天空白草案</button><button type="button" class="text-button" :disabled="value.length<=1" @click="set(value.slice(0,-1).map(day=>({...day})))">移除最后一天草案</button><button type="button" class="text-button" @click="set(null)">清除逐日草案</button></div>
    </template>
    <template v-else><p>未说明逐日安排。清除仅在保存补充后生效。</p><button type="button" class="secondary" @click="set(Array.from({length:Math.max(1,Math.min(3,count||1))},blank))">按草案天数创建空白逐日项</button></template>
    <label class="daily-select"><input type="checkbox" :checked="selected" aria-label="保存逐日时段与默认停留" @change="emit('select',($event.target as HTMLInputElement).checked)"/>保存此项</label>
  </fieldset>
</template>

<style scoped>
.draft-daily{border:1px solid var(--line);border-radius:8px;padding:14px;margin:16px 0;min-width:0}.draft-daily legend{font-size:13px;font-weight:600}.draft-daily p{font-size:11px;line-height:1.8;color:var(--muted);margin:6px 0 12px}.draft-daily h4{font-size:12px;margin:12px 0}.draft-daily section+section{border-top:1px solid var(--line);margin-top:14px}.daily-row{display:grid;grid-template-columns:1fr 1fr;gap:14px}.draft-daily label{font-size:12px;margin:8px 0;min-width:0}.draft-daily input{width:100%;box-sizing:border-box}.daily-actions{display:flex;flex-wrap:wrap;gap:10px}.daily-select{display:flex;gap:6px;align-items:center}.daily-select input{width:auto;accent-color:var(--green)}@media(max-width:680px){.daily-row{grid-template-columns:1fr}}
</style>
