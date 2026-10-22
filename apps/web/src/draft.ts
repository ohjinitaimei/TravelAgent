import type { Draft, Schema } from './api'
import type { PlanForm } from './schedules'

export type DraftField = keyof Schema<'DraftValues'>
export type ScalarDraftField=Exclude<DraftField,'day_schedules'>
export type DraftDayInput={day_start:string;day_end:string;stay_minutes:string|number|null}
export type DraftAnswers=Partial<Record<ScalarDraftField,string|number>>
export const draftFields: {key:ScalarDraftField;label:string;type:string;min?:number;max?:number;maxlength?:number}[] = [
  {key:'city',label:'目的地',type:'text'}, {key:'query',label:'地点关键词',type:'text'},
  {key:'start_date',label:'出发日期',type:'date'}, {key:'days',label:'天数',type:'number',min:1,max:3},
  {key:'stops_per_day',label:'每天站数',type:'number',min:1,max:4},
  {key:'day_start',label:'每日开始',type:'time'}, {key:'day_end',label:'每日结束',type:'time'},
  {key:'stay_minutes',label:'每站停留',type:'number',min:10,max:360},
  {key:'mode',label:'交通方式',type:'select'}, {key:'budget',label:'预算上限',type:'number',min:0},
  {key:'max_leg_travel_minutes',label:'单段交通上限（分钟）',type:'number',min:1,max:1439},
  {key:'max_daily_travel_minutes',label:'每日交通上限（分钟）',type:'number',min:1,max:1439},
  {key:'origin_hint',label:'出发地点线索',type:'text',maxlength:100},
  {key:'destination_hint',label:'返回地点线索',type:'text',maxlength:100},
]

/** Keep omissions visible. Neither text extraction nor confirmation creates route facts. */
export function draftScheduleInputs(draft:Draft):DraftDayInput[]|null {
  return draft.proposal.values.day_schedules?.map(day=>({day_start:day.day_start??'',day_end:day.day_end??'',stay_minutes:day.stay_minutes??null}))??null
}
function draftSchedules(days:DraftDayInput[]|null):Schema<'DraftValues'>['day_schedules'] {
  if(days===null)return null
  if(days.length<1||days.length>3)throw Error('逐日时段须为 1 至 3 天')
  return days.map((day,index)=>{
    const clock=(value:string)=>{
      const text=value.trim()
      if(text&&!/^([01]\d|2[0-3]):[0-5]\d$/.test(text))throw Error(`第 ${index+1} 天时段格式无效`)
      return text||null
    }
    const day_start=clock(day.day_start),day_end=clock(day.day_end)
    if(day_start&&day_end&&day_end<=day_start)throw Error(`第 ${index+1} 天结束须晚于开始，不支持跨夜`)
    const raw=day.stay_minutes==null?'':String(day.stay_minutes).trim()
    const stay_minutes=raw===''?null:Number(raw)
    if(stay_minutes!==null&&(!Number.isInteger(stay_minutes)||stay_minutes<10||stay_minutes>360))throw Error(`第 ${index+1} 天默认停留超出允许范围`)
    return {day_start,day_end,stay_minutes}
  })
}

export function displayDraftValue(name:string,value:unknown):string {
  if(name==='mode')return value==='walking'?'步行':'驾车'
  if(name==='day_schedules'&&Array.isArray(value))return value.map((day,index)=>`第 ${index+1} 天 ${day.day_start??'开始未说明'}—${day.day_end??'结束未说明'}，停留 ${day.stay_minutes==null?'未说明':`${day.stay_minutes} 分钟`}`).join('；')
  return String(value)
}

/** Send only selected user changes; omitted fields never overwrite the draft. */
export function clarificationRequest(draft:Draft, answers:DraftAnswers, selected:Partial<Record<DraftField,boolean>>, schedules?:DraftDayInput[]|null): Schema<'DraftClarificationRequest'> {
  const values:Schema<'DraftValues'>={}
  const confirm:DraftField[]=[]
  for(const field of draftFields) {
    if(!selected[field.key]) continue
    const text=String(answers[field.key]??'').trim()
    const value=text===''?null:field.type==='number'?Number(text):text
    if(typeof value==='number' && (!Number.isFinite(value)||(field.key!=='budget'&&!Number.isInteger(value))||value<(field.min??0)||value>(field.max??Infinity))) throw new Error(`${field.label}超出允许范围`)
    if(typeof value==='string'&&field.type==='text'&&value.length>(field.maxlength??(field.key==='city'?60:240)))throw new Error(`${field.label}超出允许长度`)
    if(field.key==='mode'&&value!==null&&value!=='walking'&&value!=='driving') throw new Error('请选择步行或驾车')
    if(value!==(draft.proposal.values[field.key]??null)) Object.assign(values,{[field.key]:value})
    if(value!==null&&!draft.confirmed_fields?.includes(field.key)) confirm.push(field.key)
  }
  if(selected.day_schedules) {
    if(schedules===undefined)throw Error('请核对要保存的逐日时段')
    const daily=draftSchedules(schedules)
    if(JSON.stringify(daily)!==JSON.stringify(draft.proposal.values.day_schedules??null))values.day_schedules=daily
    if(daily!==null&&!draft.confirmed_fields?.includes('day_schedules'))confirm.push('day_schedules')
  }
  const daily='day_schedules' in values?values.day_schedules:draft.proposal.values.day_schedules
  const count='days' in values?values.days:draft.proposal.values.days
  if(daily!=null&&count!=null&&daily.length!==count)throw Error('逐日时段与天数不一致，请逐项核对；不会自动增删草案')
  if(!Object.keys(values).length&&!confirm.length) throw new Error('请选择要确认或补充的字段')
  return {expected_revision:draft.revision??1,values,confirm_fields:confirm}
}

/** Applying a draft replaces earlier inputs; never submits a planning task. */
export function draftForm(draft: Draft): PlanForm {
  if(draft.proposal.values.day_schedules!=null&&draft.proposal.values.days==null)throw Error('请先在草案中确认旅行天数，再填入逐日时段')
  const defaults: PlanForm={compare_poi_alternatives:false,city:'',query:'',start_date:'',days:2,stops_per_day:3,day_start:'09:00',day_end:'18:00',stay_minutes:60,mode:'walking',budget:null,user_prices:{},stay_minutes_by_poi:{},day_schedules:null,day_endpoints:null,day_origin_poi_id:null,day_destination_poi_id:null,max_leg_travel_minutes:null,max_daily_travel_minutes:null}
  for(const [field,value] of Object.entries(draft.proposal.values)) {
    if(value!=null && field!=='day_schedules' && field in defaults) Object.assign(defaults,{[field]:value})
  }
  defaults.day_schedules=draftScheduleInputs(draft)
  return defaults
}
