import type { Itinerary } from './api'
import { editChanges, editSnapshot } from './editor'
import { dayTransport } from './journey'

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
    constraints:{...trip.request,budget:trip.request.budget},defaultStay:trip.request.stay_minutes,optimize:false})
}
export function versionMetrics(trip:Itinerary) {
  const stops=trip.days.flatMap(day=>day.stops)
  const days=trip.days.map(day=>dayTransport(day,trip.request))
  const sum=(key:'interstop'|'boundary'|'total'|'distance')=>days.some(day=>day[key]===null)?null:days.reduce((n,day)=>n+day[key]!,0)
  return {stops:stops.length,stay:stops.reduce((sum,stop)=>sum+stop.stay_minutes,0),
    travel:sum('total'),interstopTravel:sum('interstop'),boundaryTravel:sum('boundary'),distance:sum('distance'),
    knownCost:trip.budget.known_subtotal,totalCost:trip.budget.total??null,
    missingStationCosts:stops.filter(stop=>stop.user_cost==null).length}
}
export function versionChanges(parent:Itinerary,child:Itinerary) {
  if(child.parent_id!==parent.id||child.id===parent.id)throw new Error('版本来源不匹配，未生成对照。')
  const names=new Map([...parent.days,...child.days].flatMap(day=>[...day.stops.map(stop=>stop.poi),day.origin_poi,day.destination_poi].filter(poi=>poi!=null).map(poi=>[poi.id,poi.name] as const)))
  return editChanges(snapshot(parent),snapshot(child),id=>names.get(id)??id)
    .map(change=>({...change,label:change.label==='新增站点默认停留'?'默认停留':change.label}))
}
