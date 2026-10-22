import type { Itinerary } from './api'

/** Select already saved facts for display and navigation; no route estimation. */
export function planningChanges(trip:Itinerary) {
  const summary=trip.planning_comparison
  if(!summary)return []
  return trip.days.map((day,index)=>{
    const original=summary.baseline_days[index]?.stops??[]
    const old=new Set(original.map(stop=>stop.poi.id)),current=new Set(day.stops.map(stop=>stop.poi.id))
    return {day:index+1,removed:original.filter(stop=>!current.has(stop.poi.id)).map(stop=>stop.poi.name),
      added:day.stops.filter(stop=>!old.has(stop.poi.id)).map(stop=>stop.poi.name),
      orderChanged:original.map(stop=>stop.poi.id).join('\0')!==day.stops.map(stop=>stop.poi.id).join('\0')}
  }).filter(day=>day.orderChanged)
}
export function longestSavedLeg(trip:Itinerary) {
  const legs=trip.days.flatMap((day,index)=>[day.origin_segment,...day.stops.map(stop=>stop.travel_to_next),day.destination_segment]
    .filter(leg=>leg!=null).map(leg=>({day:index,id:leg.origin_id,minutes:leg.duration_min})))
  return legs.reduce<typeof legs[number]|null>((best,leg)=>!best||leg.minutes>best.minutes?leg:best,null)
}


export function planningRatings(trip:Itinerary) {
  if(!trip.planning_comparison)return []
  const original=trip.planning_comparison?.baseline_days.flatMap(day=>day.stops.map(stop=>stop.poi))??[]
  const current=trip.days.flatMap(day=>day.stops.map(stop=>stop.poi))
  const oldIds=new Set(original.map(p=>p.id)),newIds=new Set(current.map(p=>p.id))
  return [...original.filter(p=>!newIds.has(p.id)).map(p=>({kind:'原地点',name:p.name,rating:p.rating??null})),
    ...current.filter(p=>!oldIds.has(p.id)).map(p=>({kind:'采用地点',name:p.name,rating:p.rating??null}))]
}
