import { cloneSchedules, scheduleAt, type ScheduleInput } from './schedules'
import { cloneEndpoints, endpointAt, type DayEndpoints } from './endpoints'
/** Vue number inputs may emit a number even without v-model.number. */
export function userPrices(ids: string[], values: Record<string,string|number>): Record<string,number> {
  const prices: Record<string,number>={}
  for(const id of ids) {
    const raw=values[id]
    if(raw===undefined || String(raw).trim()==='') continue
    const value=Number(raw)
    if(!Number.isFinite(value)||value<0) throw new Error('费用必须为非负数字')
    prices[id]=value
  }
  return prices
}

export type Value = string|number|null|undefined
export function travelLimits(value:{max_leg_travel_minutes?:Value;max_daily_travel_minutes?:Value}) {
  const limit=(raw:Value)=>{
    if(raw==null||raw==='')return null
    if(typeof raw!=='number'||!Number.isInteger(raw)||raw<1||raw>1439)throw Error('交通上限须为 1 至 1439 分钟的整数，留空表示不限制')
    return raw
  }
  return {max_leg_travel_minutes:limit(value.max_leg_travel_minutes),max_daily_travel_minutes:limit(value.max_daily_travel_minutes)}
}
export type EditInput = {
  groups:string[][]; prices:Record<string,Value>; durations:Record<string,Value>
  constraints:{start_date:string;day_start:string;day_end:string;mode:string;budget:Value;max_leg_travel_minutes?:Value;max_daily_travel_minutes?:Value;day_origin_poi_id?:string|null;day_destination_poi_id?:string|null;day_endpoints?:DayEndpoints[]|null;day_schedules?:ScheduleInput[]|null}
  defaultStay:Value; optimize:boolean
}
export type EditSnapshot = {
  groups:string[][]; prices:Record<string,Value>; durations:Record<string,Value>
  start_date:string;day_start:string;day_end:string;mode:string;budget:Value;defaultStay:Value;optimize:boolean
  max_leg_travel_minutes:Value;max_daily_travel_minutes:Value
  day_origin_poi_id:string|null;day_destination_poi_id:string|null
  day_schedules:ScheduleInput[]|null
  day_endpoints:DayEndpoints[]|null
}
export type EditChange = {label:string;before:string;after:string}

function numeric(value:Value):string|number|null {
  if(value==null||String(value).trim()==='') return null
  const number=Number(value)
  return Number.isFinite(number)?number:String(value)
}

/** Canonical user input only: no POI facts, traffic estimates or tokens. */
export function editSnapshot(input:EditInput):EditSnapshot {
  const ids=[...new Set(input.groups.flat())].sort()
  return {groups:input.groups.map(day=>[...day]),
    prices:Object.fromEntries(ids.map(id=>[id,numeric(input.prices[id])])),
    durations:Object.fromEntries(ids.map(id=>[id,numeric(input.durations[id]??scheduleAt({...input.constraints,stay_minutes:input.defaultStay},input.groups.findIndex(day=>day.includes(id)))?.stay_minutes)])),
    start_date:input.constraints.start_date,day_start:input.constraints.day_start,day_end:input.constraints.day_end,
    mode:input.constraints.mode,budget:numeric(input.constraints.budget),defaultStay:numeric(input.defaultStay),optimize:input.optimize,
    max_leg_travel_minutes:numeric(input.constraints.max_leg_travel_minutes),max_daily_travel_minutes:numeric(input.constraints.max_daily_travel_minutes),
    day_origin_poi_id:input.constraints.day_origin_poi_id??null,day_destination_poi_id:input.constraints.day_destination_poi_id??null,day_endpoints:cloneEndpoints(input.constraints.day_endpoints),day_schedules:cloneSchedules(input.constraints.day_schedules)}
}

export function editChanges(before:EditSnapshot,after:EditSnapshot,name:(id:string)=>string):EditChange[] {
  const changes:EditChange[]=[]
  const positions=(groups:string[][])=>new Map(groups.flatMap((day,d)=>day.map((id,i)=>[id,{day:d,index:i}] as const)))
  const old=positions(before.groups), current=positions(after.groups)
  const position=(value:{day:number;index:number})=>`第 ${value.day+1} 天第 ${value.index+1} 站`
  const text=(value:Value,unit='')=>value==null?'未知':`${value}${unit}`
  for(const [id,place] of old) if(!current.has(id)) changes.push({label:`移除 ${name(id)}`,before:position(place),after:'已移除'})
  for(const [id,place] of current) {
    const previous=old.get(id)
    if(!previous) changes.push({label:`新增 ${name(id)}`,before:'未在行程中',after:position(place)})
    else if(previous.day!==place.day||previous.index!==place.index) changes.push({label:`位置 ${name(id)}`,before:position(previous),after:position(place)})
    if(previous&&before.durations[id]!==after.durations[id]) changes.push({label:`停留 ${name(id)}`,before:text(before.durations[id],' 分钟'),after:text(after.durations[id],' 分钟')})
    if((previous?before.prices[id]:null)!==after.prices[id]) changes.push({label:`费用 ${name(id)}`,before:text(previous?before.prices[id]:null,' 元'),after:text(after.prices[id],' 元')})
  }
  const labels={max_leg_travel_minutes:'单段交通上限',max_daily_travel_minutes:'每日交通上限',start_date:'出发日期',day_start:'每日开始',day_end:'每日结束',mode:'交通方式',budget:'预算上限',defaultStay:'新增站点默认停留',optimize:'日内重新排序'} as const
  if(before.day_endpoints!=null||after.day_endpoints!=null) {
    if(Boolean(before.day_endpoints)!==Boolean(after.day_endpoints))changes.push({label:'起终点设置方式',before:before.day_endpoints?'逐日独立':'所有日期共用',after:after.day_endpoints?'逐日独立':'所有日期共用'})
    for(let index=0;index<after.groups.length;index++)for(const [key,label] of [['origin_poi_id','出发地'],['destination_poi_id','返回地']] as const) {
      const old=endpointAt(before,index)?.[key]??null,current=endpointAt(after,index)?.[key]??null
      if(old!==current)changes.push({label:`第 ${index+1} 天${label}`,before:old?name(old):'未设置',after:current?name(current):'未设置'})
    }
  } else for(const [key,label] of [['day_origin_poi_id','出发地'],['day_destination_poi_id','返回地']] as const) {
    if((before[key]??null)!==(after[key]??null))changes.push({label,before:before[key]?name(before[key]):'未设置',after:after[key]?name(after[key]):'未设置'})
  }
  if(before.day_schedules!=null||after.day_schedules!=null) {
    if(Boolean(before.day_schedules)!==Boolean(after.day_schedules))changes.push({label:'时段设置方式',before:before.day_schedules?'逐日独立':'所有日期共用',after:after.day_schedules?'逐日独立':'所有日期共用'})
    for(let index=0;index<after.groups.length;index++)for(const [key,label] of [['day_start','开始'],['day_end','结束'],['stay_minutes','默认停留']] as const) {
      const old=scheduleAt({...before,stay_minutes:before.defaultStay},index)?.[key],current=scheduleAt({...after,stay_minutes:after.defaultStay},index)?.[key]
      if(old!==current)changes.push({label:`第 ${index+1} 天${label}`,before:text(old,key==='stay_minutes'?' 分钟':''),after:text(current,key==='stay_minutes'?' 分钟':'')})
    }
  }
  for(const key of Object.keys(labels) as (keyof typeof labels)[]) if(before[key]!==after[key]) {
    const show=(snapshot:EditSnapshot)=>{
      if(key==='max_leg_travel_minutes'||key==='max_daily_travel_minutes')return snapshot[key]==null?'未设置':text(snapshot[key],' 分钟')
      return key==='mode'?({walking:'步行',driving:'驾车'}[snapshot.mode]??snapshot.mode):key==='optimize'?(snapshot.optimize?'开启':'关闭'):text(snapshot[key] as Value,key==='budget'?' 元':key==='defaultStay'?' 分钟':'')
    }
    changes.push({label:labels[key],before:show(before),after:show(after)})
  }
  return changes
}
