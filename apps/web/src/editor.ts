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

type Value = string|number|null|undefined
export type EditInput = {
  groups:string[][]; prices:Record<string,Value>; durations:Record<string,Value>
  constraints:{start_date:string;day_start:string;day_end:string;mode:string;budget:Value}
  defaultStay:Value; optimize:boolean
}
export type EditSnapshot = {
  groups:string[][]; prices:Record<string,Value>; durations:Record<string,Value>
  start_date:string;day_start:string;day_end:string;mode:string;budget:Value;defaultStay:Value;optimize:boolean
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
    durations:Object.fromEntries(ids.map(id=>[id,numeric(input.durations[id]??input.defaultStay)])),
    start_date:input.constraints.start_date,day_start:input.constraints.day_start,day_end:input.constraints.day_end,
    mode:input.constraints.mode,budget:numeric(input.constraints.budget),defaultStay:numeric(input.defaultStay),optimize:input.optimize}
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
  const labels={start_date:'出发日期',day_start:'每日开始',day_end:'每日结束',mode:'交通方式',budget:'预算上限',defaultStay:'新增站点默认停留',optimize:'日内重新排序'} as const
  for(const key of Object.keys(labels) as (keyof typeof labels)[]) if(before[key]!==after[key]) {
    const show=(snapshot:EditSnapshot)=>key==='mode'?({walking:'步行',driving:'驾车'}[snapshot.mode]??snapshot.mode):key==='optimize'?(snapshot.optimize?'开启':'关闭'):text(snapshot[key] as Value,key==='budget'?' 元':key==='defaultStay'?' 分钟':'')
    changes.push({label:labels[key],before:show(before),after:show(after)})
  }
  return changes
}
