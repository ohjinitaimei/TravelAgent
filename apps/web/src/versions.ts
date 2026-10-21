import type { Itinerary } from './api'
import { editChanges, editSnapshot } from './editor'

export type VersionFilter = { query: string; kind: 'all'|'original'|'adjusted'; order: 'newest'|'oldest'|'departure'; parentId: string|null }
export function shortVersion(id: string) { return id.slice(0, 8) }
export function versionTime(value?: string|null) {
  const date = new Date(value??'')
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', {hour12:false}) : '保存时间未提供'
}
export function filterVersions(trips: Itinerary[], filter: VersionFilter): Itinerary[] {
  const query=filter.query.trim().toLocaleLowerCase()
  const created=(value:Itinerary)=>{const time=Date.parse(value.created_at??'');return Number.isFinite(time)?time:null}
  return trips.filter(trip=>(filter.kind==='all'||Boolean(trip.parent_id)===(filter.kind==='adjusted'))
    &&(!filter.parentId||trip.parent_id===filter.parentId)
    &&(!query||[trip.title,trip.request.city,trip.request.start_date,trip.id].some(value=>value.toLocaleLowerCase().includes(query))))
    .sort((a,b)=>{
      if(filter.order==='departure') {const delta=a.request.start_date.localeCompare(b.request.start_date);if(delta)return delta}
      const x=created(a),y=created(b)
      if(x===null||y===null)return x===y?0:x===null?1:-1
      return filter.order==='oldest'?x-y:y-x
    })
}
export function directVersions(trips:Itinerary[], id:string) {return trips.filter(trip=>trip.parent_id===id&&trip.id!==id)}
function snapshot(trip:Itinerary) {
  const stops=trip.days.flatMap(day=>day.stops)
  return editSnapshot({groups:trip.days.map(day=>day.stops.map(stop=>stop.poi.id)),
    prices:Object.fromEntries(stops.map(stop=>[stop.poi.id,stop.user_cost])),
    durations:Object.fromEntries(stops.map(stop=>[stop.poi.id,stop.stay_minutes])),
    constraints:{start_date:trip.request.start_date,day_start:trip.request.day_start,day_end:trip.request.day_end,mode:trip.request.mode,budget:trip.request.budget},defaultStay:trip.request.stay_minutes,optimize:false})
}
export function versionMetrics(trip:Itinerary) {
  const stops=trip.days.flatMap(day=>day.stops)
  const complete=trip.days.every(day=>day.stops.every((stop,index)=>{
    const next=day.stops[index+1],route=stop.travel_to_next
    return next?Boolean(route&&route.origin_id===stop.poi.id&&route.destination_id===next.poi.id):!route
  }))
  return {stops:stops.length,stay:stops.reduce((sum,stop)=>sum+stop.stay_minutes,0),
    travel:complete?stops.reduce((sum,stop)=>sum+(stop.travel_to_next?.duration_min??0),0):null,
    distance:complete?stops.reduce((sum,stop)=>sum+(stop.travel_to_next?.distance_km??0),0):null,
    knownCost:trip.budget.known_subtotal,totalCost:trip.budget.total??null,
    missingStationCosts:stops.filter(stop=>stop.user_cost==null).length}
}
export function versionChanges(parent:Itinerary,child:Itinerary) {
  if(child.parent_id!==parent.id||child.id===parent.id)throw new Error('版本来源不匹配，未生成对照。')
  const names=new Map([...parent.days,...child.days].flatMap(day=>day.stops.map(stop=>[stop.poi.id,stop.poi.name] as const)))
  return editChanges(snapshot(parent),snapshot(child),id=>names.get(id)??id)
    .map(change=>({...change,label:change.label==='新增站点默认停留'?'默认停留':change.label}))
}
