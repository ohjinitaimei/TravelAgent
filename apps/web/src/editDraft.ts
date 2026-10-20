import { editSnapshot, type EditSnapshot } from './editor'
import type { Itinerary } from './api'

const MAX_AGE=7*24*60*60*1000
const MAX_SIZE=32_768
export const editDraftKey=(owner:string)=>`travelagent.edit.v1.${encodeURIComponent(owner)}`
export type EditDraft={version:1;sourceId:string;sourceCreatedAt:string;baseline:EditSnapshot;value:EditSnapshot;day:number;updatedAt:number}
const object=(v:unknown):v is Record<string,unknown>=>Boolean(v)&&typeof v==='object'&&!Array.isArray(v)
const id=(v:unknown):v is string=>typeof v==='string'&&v.length>0&&v.length<=128&&!['__proto__','constructor','prototype'].includes(v)
function snapshot(v:unknown):EditSnapshot {
  if(!object(v)||!Array.isArray(v.groups)||v.groups.length<1||v.groups.length>3) throw Error('invalid')
  const groups=v.groups.map(day=>{if(!Array.isArray(day)||day.length>4||!day.every(id))throw Error('invalid');return [...day] as string[]})
  const ids=groups.flat()
  if(new Set(ids).size!==ids.length)throw Error('invalid')
  const scalar=(value:unknown)=>{
    if(value===null||typeof value==='number'&&Number.isFinite(value)||typeof value==='string'&&value.length<=64)return value
    throw Error('invalid')
  }
  const fields=(raw:unknown)=>{if(!object(raw))throw Error('invalid');return Object.fromEntries([...ids].sort().map(key=>[key,scalar(raw[key])]))}
  const text=(key:string)=>{if(typeof v[key]!=='string'||v[key].length>32)throw Error('invalid');return v[key] as string}
  if(!['walking','driving'].includes(String(v.mode))||typeof v.optimize!=='boolean')throw Error('invalid')
  return {groups,prices:fields(v.prices),durations:fields(v.durations),start_date:text('start_date'),day_start:text('day_start'),day_end:text('day_end'),mode:String(v.mode),budget:scalar(v.budget),defaultStay:scalar(v.defaultStay),optimize:v.optimize}
}
export function parseEditDraft(raw:string,now=Date.now()):EditDraft {
  if(raw.length>MAX_SIZE)throw Error('草稿过大，无法恢复；可放弃本机草稿后重新编辑。')
  try {
    const v:unknown=JSON.parse(raw)
    if(!object(v)||v.version!==1||!id(v.sourceId)||typeof v.sourceCreatedAt!=='string'||v.sourceCreatedAt.length>64||typeof v.updatedAt!=='number'||!Number.isFinite(v.updatedAt)||v.updatedAt>now+60_000)throw Error('invalid')
    if(now-v.updatedAt>MAX_AGE)throw Error('expired')
    const value=snapshot(v.value),baseline=snapshot(v.baseline)
    if(value.groups.length!==baseline.groups.length||!Number.isInteger(v.day)||Number(v.day)<0||Number(v.day)>=value.groups.length)throw Error('invalid')
    return {version:1,sourceId:v.sourceId,sourceCreatedAt:v.sourceCreatedAt,baseline,value,day:Number(v.day),updatedAt:v.updatedAt}
  } catch(e) {
    throw Error(e instanceof Error&&e.message==='expired'?'本机编辑草稿已超过 7 天，请放弃后重新编辑。':'本机编辑草稿格式无效，无法恢复；可放弃后重新编辑。')
  }
}
export function itineraryBaseline(trip:Itinerary):EditSnapshot {
  const stops=trip.days.flatMap(day=>day.stops)
  return editSnapshot({groups:trip.days.map(day=>day.stops.map(stop=>stop.poi.id)),prices:Object.fromEntries(stops.map(stop=>[stop.poi.id,stop.user_cost??null])),durations:Object.fromEntries(stops.map(stop=>[stop.poi.id,stop.stay_minutes])),constraints:{...trip.request,budget:trip.request.budget??null},defaultStay:trip.request.stay_minutes,optimize:false})
}
export function verifyEditSource(draft:EditDraft,trip:Itinerary) {
  if(trip.id!==draft.sourceId||(trip.created_at??'')!==draft.sourceCreatedAt||JSON.stringify(itineraryBaseline(trip))!==JSON.stringify(draft.baseline))throw Error('原行程版本与草稿不一致，请放弃本机草稿后重新编辑。')
}
export class EditDraftConflict extends Error {
  constructor(){super('本机草稿已在其他页面变化。请刷新页面后恢复最新草稿，避免覆盖。')}
}

/** One draft per account. Compare the last observed raw value before every write/delete. */
export class EditDraftStore {
  draft:EditDraft|null=null
  issue=''
  unavailable=false
  private expected:string|null=null
  constructor(private owner:string) {
    try {this.expected=localStorage.getItem(editDraftKey(owner))}
    catch {this.unavailable=true;this.issue='浏览器无法读取本机草稿；仍可编辑并直接保存行程。';return}
    try {if(this.expected)this.draft=parseEditDraft(this.expected)}
    catch(e) {this.issue=e instanceof Error?e.message:'本机存储不可用'}
  }
  check() {
    if(localStorage.getItem(editDraftKey(this.owner))!==this.expected)throw new EditDraftConflict()
  }
  write(value:EditDraft) {
    this.check()
    const raw=JSON.stringify(value),clean=parseEditDraft(raw)
    localStorage.setItem(editDraftKey(this.owner),JSON.stringify(clean))
    this.expected=JSON.stringify(clean);this.draft=clean;this.issue='';this.unavailable=false
  }
  clear() {
    this.check();localStorage.removeItem(editDraftKey(this.owner));this.expected=null;this.draft=null;this.issue=''
  }
}
