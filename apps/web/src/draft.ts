import type { Draft, PlanRequest, Schema } from './api'

export type DraftField = keyof Schema<'DraftValues'>
export const draftFields: {key:DraftField;label:string;type:string;min?:number;max?:number}[] = [
  {key:'city',label:'目的地',type:'text'}, {key:'query',label:'地点关键词',type:'text'},
  {key:'start_date',label:'出发日期',type:'date'}, {key:'days',label:'天数',type:'number',min:1,max:3},
  {key:'stops_per_day',label:'每天站数',type:'number',min:1,max:4},
  {key:'day_start',label:'每日开始',type:'time'}, {key:'day_end',label:'每日结束',type:'time'},
  {key:'stay_minutes',label:'每站停留',type:'number',min:10,max:360},
  {key:'mode',label:'交通方式',type:'select'}, {key:'budget',label:'预算上限',type:'number',min:0},
]

/** Send only selected user changes; omitted fields never overwrite the draft. */
export function clarificationRequest(draft:Draft, answers:Partial<Record<DraftField,string|number>>, selected:Partial<Record<DraftField,boolean>>): Schema<'DraftClarificationRequest'> {
  const values:Schema<'DraftValues'>={}
  const confirm:DraftField[]=[]
  for(const field of draftFields) {
    if(!selected[field.key]) continue
    const text=String(answers[field.key]??'').trim()
    const value=text===''?null:field.type==='number'?Number(text):text
    if(typeof value==='number' && (!Number.isFinite(value)||(field.key!=='budget'&&!Number.isInteger(value))||value<(field.min??0)||value>(field.max??Infinity))) throw new Error(`${field.label}超出允许范围`)
    if(field.key==='mode'&&value!==null&&value!=='walking'&&value!=='driving') throw new Error('请选择步行或驾车')
    if(value!==(draft.proposal.values[field.key]??null)) Object.assign(values,{[field.key]:value})
    if(value!==null&&!draft.confirmed_fields?.includes(field.key)) confirm.push(field.key)
  }
  if(!Object.keys(values).length&&!confirm.length) throw new Error('请选择要确认或补充的字段')
  return {expected_revision:draft.revision??1,values,confirm_fields:confirm}
}

/** Applying a draft replaces earlier inputs; never submits a planning task. */
export function draftForm(draft: Draft): PlanRequest {
  const defaults: PlanRequest={city:'',query:'',start_date:'',days:2,stops_per_day:3,day_start:'09:00',day_end:'18:00',stay_minutes:60,mode:'walking',budget:null,user_prices:{},stay_minutes_by_poi:{},day_schedules:null,day_endpoints:null,day_origin_poi_id:null,day_destination_poi_id:null,max_leg_travel_minutes:null,max_daily_travel_minutes:null}
  for(const [field,value] of Object.entries(draft.proposal.values)) {
    if(value!=null && field in defaults) Object.assign(defaults,{[field]:value})
  }
  return defaults
}
