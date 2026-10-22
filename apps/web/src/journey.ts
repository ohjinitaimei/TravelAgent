import type { Itinerary, PlanRequest } from './api'

/** Presentation totals from saved facts only; missing necessary routes remain unknown. */
export function dayTransport(day:Itinerary['days'][number],request?:PlanRequest) {
  const between=day.stops.flatMap(stop=>stop.travel_to_next?[stop.travel_to_next]:[])
  const interstopComplete=day.stops.every((stop,index)=>{
    const next=day.stops[index+1],leg=stop.travel_to_next
    return next?Boolean(leg&&leg.origin_id===stop.poi.id&&leg.destination_id===next.poi.id):!leg
  })
  const origin=day.origin_poi,destination=day.destination_poi,first=day.stops[0]?.poi,last=day.stops.at(-1)?.poi
  const boundaryComplete=Boolean(first&&last)
    &&(!request||((request.day_origin_poi_id??null)===(origin?.id??null)&&(request.day_destination_poi_id??null)===(destination?.id??null)))
    &&(origin?(origin.id===first?.id?!day.origin_segment:Boolean(day.origin_segment&&day.origin_segment.origin_id===origin.id&&day.origin_segment.destination_id===first?.id)):!day.origin_segment)
    &&(destination?(destination.id===last?.id?!day.destination_segment:Boolean(day.destination_segment&&day.destination_segment.origin_id===last?.id&&day.destination_segment.destination_id===destination.id)):!day.destination_segment)
  const boundary=[day.origin_segment,day.destination_segment].filter(leg=>leg!=null)
  const interstop=interstopComplete?between.reduce((n,leg)=>n+leg.duration_min,0):null
  const boundaryMinutes=boundaryComplete?boundary.reduce((n,leg)=>n+leg.duration_min,0):null
  return {interstop,boundary:boundaryMinutes,total:interstop!==null&&boundaryMinutes!==null?interstop+boundaryMinutes:null,
    distance:interstopComplete&&boundaryComplete?[...between,...boundary].reduce((n,leg)=>n+leg.distance_km,0):null}
}
