import type { Draft } from './api'
import { endpointAt } from './endpoints'
import type { PlanForm } from './schedules'

export type HandoffDecision={key:string;policy:'selected'|'form_only'}

/** Bind a user's decision to this exact draft revision and selected anchors. No provider facts. */
export function handoffKey(draft:Draft,form:PlanForm):string {
  return JSON.stringify([draft.id,draft.revision??1,form.city,form.start_date,form.days??2,
    Array.from({length:form.days??2},(_,index)=>{
      const day=endpointAt(form,index)
      return [day?.origin_poi_id??null,day?.destination_poi_id??null]
    })])
}
export function needsHandoff(draft:Draft):boolean {
  return Boolean(draft.proposal.values.origin_hint||draft.proposal.values.destination_hint)
}
/** A selected ID comes from the existing real POI picker; text hints never become IDs. */
export function handoffAnchorsReady(draft:Draft,form:PlanForm):boolean {
  const values=draft.proposal.values
  return Array.from({length:form.days??2},(_,index)=>endpointAt(form,index)).every(day=>
    (!values.origin_hint||Boolean(day?.origin_poi_id))&&(!values.destination_hint||Boolean(day?.destination_poi_id)))
}
export function handoffAccepted(draft:Draft,form:PlanForm,decision?:HandoffDecision|null):boolean {
  if(!needsHandoff(draft))return true
  return decision?.key===handoffKey(draft,form)&&
    (decision.policy==='form_only'||decision.policy==='selected'&&handoffAnchorsReady(draft,form))
}
