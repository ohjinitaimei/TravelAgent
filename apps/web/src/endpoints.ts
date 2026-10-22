import type { PlanRequest, Schema } from './api'

export type DayEndpoints=Schema<'DayEndpoints'>
export type EndpointOptions=Pick<PlanRequest,'day_origin_poi_id'|'day_destination_poi_id'|'day_endpoints'>
export function endpointAt(value:EndpointOptions,index:number):DayEndpoints|undefined {
  return value.day_endpoints!=null?value.day_endpoints[index]:{
    origin_poi_id:value.day_origin_poi_id??null,destination_poi_id:value.day_destination_poi_id??null,
  }
}
export function cloneEndpoints(value:DayEndpoints[]|null|undefined):DayEndpoints[]|null {
  return value?.map(day=>({origin_poi_id:day.origin_poi_id??null,destination_poi_id:day.destination_poi_id??null}))??null
}
export function selectedAnchorIds(value:EndpointOptions):string[] {
  const days=value.day_endpoints??[endpointAt(value,0)!]
  return [...new Set(days.flatMap(day=>[day.origin_poi_id,day.destination_poi_id]).filter((id):id is string=>Boolean(id)))]
}
/** Only bounded user-selected IDs may enter local drafts; no provider facts. */
export function parseEndpoints(value:unknown,count:number):DayEndpoints[]|null {
  if(value==null)return null
  if(!Array.isArray(value)||value.length!==count||count<1||count>3)throw Error('逐日起终点与天数不一致')
  return value.map(day=>{
    if(!day||typeof day!=='object'||Array.isArray(day)||Object.keys(day).some(key=>!['origin_poi_id','destination_poi_id'].includes(key)))throw Error('逐日起终点格式无效')
    const id=(key:string)=>{
      const id=day[key]
      if(id==null)return null
      if(typeof id!=='string'||!id.trim()||id.length>100||['__proto__','constructor','prototype'].includes(id))throw Error('逐日起终点 ID 无效')
      return id
    }
    return {origin_poi_id:id('origin_poi_id'),destination_poi_id:id('destination_poi_id')}
  })
}
