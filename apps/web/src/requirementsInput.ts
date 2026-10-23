import type { Draft, Schema } from './api'
import { draftFields, draftScheduleInputs, type DraftAnswers, type DraftDayInput, type DraftField, type ScalarDraftField } from './draft'

type SchedulePatch={count?:number|null;days:Record<string,Partial<DraftDayInput>>}
export type RequirementsInput={text:string|null;clarification:{sourceId:string;sourceRevision:number;answers:DraftAnswers;selected:Partial<Record<DraftField,boolean>>;schedulePatch:SchedulePatch|null}|null}
export type StoredRequirementsInput={version:1;input:RequirementsInput;updatedAt:number}
export type RequirementsReview={answers:DraftAnswers;schedules:DraftDayInput[]|null;selected:Partial<Record<DraftField,boolean>>}
const MAX_AGE=7*24*60*60*1000,MAX_SIZE=32_768
export const requirementsInputKey=(owner:string)=>`travelagent.requirements.v1.${encodeURIComponent(owner)}`
export const emptyRequirementsInput=():RequirementsInput=>({text:null,clarification:null})
export function cloneRequirementsInput(input:RequirementsInput):RequirementsInput {
  const source=input.clarification,patch=source?.schedulePatch
  return {text:input.text,clarification:source?{...source,answers:{...source.answers},selected:{...source.selected},schedulePatch:patch?
    {...patch,days:Object.fromEntries(Object.entries(patch.days).map(([index,day])=>[index,{...day}]))}:null}:null}
}
export const requirementsHasChanges=(input:RequirementsInput)=>input.text!==null||Boolean(input.clarification&&
  (Object.keys(input.clarification.answers).length||Object.values(input.clarification.selected).some(Boolean)||input.clarification.schedulePatch))
function compact(input:RequirementsInput):RequirementsInput {
  const source=input.clarification
  if(!source)return input
  for(const [field,value] of Object.entries(source.selected))if(!value&&!(field in source.answers)&&!(field==='day_schedules'&&source.schedulePatch))delete source.selected[field as DraftField]
  if(!Object.keys(source.answers).length&&!Object.keys(source.selected).length&&!source.schedulePatch)input.clarification=null
  return input
}
export const requirementsText=(input:RequirementsInput,draft:Draft|null)=>input.text??draft?.input.text??''
export function requirementsSourceMatches(input:RequirementsInput,draft:Draft|null):boolean {
  const source=input.clarification
  return !source||Boolean(draft&&source.sourceId===draft.id&&source.sourceRevision===(draft.revision??1))
}
/** Rebuild displayed answers from the current server source plus user changes only. */
export function requirementsReview(input:RequirementsInput,draft:Draft):RequirementsReview|null {
  if(!requirementsSourceMatches(input,draft))return null
  const change=input.clarification
  const answers:DraftAnswers=Object.fromEntries(draftFields.map(field=>[field.key,String(draft.proposal.values[field.key]??'')]))
  Object.assign(answers,change?.answers)
  let schedules=draftScheduleInputs(draft)
  const patch=change?.schedulePatch
  if(patch){
    if(patch.count===null)schedules=null
    else{
      const count=patch.count??schedules?.length??0
      if(!count||Object.keys(patch.days).some(index=>Number(index)>=count))return null
      schedules=Array.from({length:count},(_,index)=>({...schedules?.[index]??{day_start:'',day_end:'',stay_minutes:null},...patch.days[String(index)]}))
    }
  }
  return {answers,schedules,selected:{...change?.selected}}
}
function edit(input:RequirementsInput,draft:Draft){
  if(!requirementsSourceMatches(input,draft))throw Error('未保存补充与当前草案版本不一致，请先核对或放弃原补充。')
  const next=cloneRequirementsInput(input)
  next.clarification??={sourceId:draft.id,sourceRevision:draft.revision??1,answers:{},selected:{},schedulePatch:null}
  return next as RequirementsInput&{clarification:NonNullable<RequirementsInput['clarification']>}
}
export const setRequirementsText=(input:RequirementsInput,text:string):RequirementsInput=>({...cloneRequirementsInput(input),text})
export function setRequirementsAnswer(input:RequirementsInput,draft:Draft,key:ScalarDraftField,value:string|number):RequirementsInput {
  const next=edit(input,draft)
  if(String(value)===String(draft.proposal.values[key]??''))delete next.clarification.answers[key]
  else next.clarification.answers[key]=value
  next.clarification.selected[key]=true
  return compact(next)
}
export function setRequirementsSelected(input:RequirementsInput,draft:Draft,key:DraftField,value:boolean):RequirementsInput {
  const next=edit(input,draft);next.clarification.selected[key]=value;return compact(next)
}
export function setRequirementsSchedules(input:RequirementsInput,draft:Draft,value:DraftDayInput[]|null):RequirementsInput {
  const next=edit(input,draft),base=draftScheduleInputs(draft)
  const patch:SchedulePatch={days:{}}
  if(value===null)patch.count=null
  else{
    if(value.length!==base?.length)patch.count=value.length
    for(const [index,day] of value.entries()){
      const prior=base?.[index]??{day_start:'',day_end:'',stay_minutes:null}
      const fields:Partial<DraftDayInput>={}
      for(const key of ['day_start','day_end','stay_minutes'] as const)if(day[key]!==prior[key])Object.assign(fields,{[key]:day[key]})
      if(Object.keys(fields).length)patch.days[String(index)]=fields
    }
  }
  next.clarification.schedulePatch=patch.count!==undefined||Object.keys(patch.days).length?patch:null
  next.clarification.selected.day_schedules=true
  return compact(next)
}
export function selectRequirementsFilled(input:RequirementsInput,draft:Draft):RequirementsInput {
  const next=edit(input,draft),view=requirementsReview(next,draft)
  if(!view)throw Error('请先核对补充对应的草案版本。')
  for(const field of draftFields)next.clarification.selected[field.key]=Boolean(String(view.answers[field.key]??'').trim())
  next.clarification.selected.day_schedules=view.schedules!==null
  return compact(next)
}
export function ackRequirementsText(input:RequirementsInput,submittedText:string):RequirementsInput {
  return input.text===submittedText?{...cloneRequirementsInput(input),text:null}:input
}
export function ackRequirementsReview(input:RequirementsInput,before:Draft,after:Draft,request:Schema<'DraftClarificationRequest'>):RequirementsInput {
  const source=input.clarification,revision=before.revision??1
  if(!source||source.sourceId!==before.id||source.sourceRevision!==revision||request.expected_revision!==revision||
    after.id!==before.id||(after.revision??1)!==revision+1)return input
  const equal=(left:unknown,right:unknown)=>JSON.stringify(left??null)===JSON.stringify(right??null)
  const values=request.values??{},confirmed=request.confirm_fields??[]
  // A source/revision match alone is insufficient proof that the selected values were saved.
  if(Object.entries(values).some(([key,value])=>!equal(value,after.proposal.values[key as DraftField]))||
    confirmed.some(key=>!after.confirmed_fields?.includes(key)))return input
  const next=cloneRequirementsInput(input),remaining=next.clarification!
  const submitted=new Set<DraftField>([...Object.keys(values) as DraftField[],...confirmed])
  for(const key of submitted){
    delete remaining.answers[key as ScalarDraftField];delete remaining.selected[key]
    if(key==='day_schedules')remaining.schedulePatch=null
  }
  for(const [key,selected] of Object.entries(remaining.selected)){
    const field=key as DraftField
    if(selected&&!(field in remaining.answers)&&!(field==='day_schedules'&&remaining.schedulePatch)&&
      before.confirmed_fields?.includes(field)&&after.confirmed_fields?.includes(field)&&
      equal(before.proposal.values[field],after.proposal.values[field]))delete remaining.selected[field]
  }
  const fields=new Set<DraftField>([...Object.keys(remaining.answers) as DraftField[],...Object.keys(remaining.selected) as DraftField[]])
  if(remaining.schedulePatch)fields.add('day_schedules')
  // Only this known, atomic PATCH may advance a retained edit. Any changed baseline
  // stays bound to the old revision so normal source-conflict handling can protect it.
  if([...fields].every(field=>equal(before.proposal.values[field],after.proposal.values[field])))remaining.sourceRevision=after.revision??revision+1
  return compact(next)
}
export const clearRequirementsReview=(input:RequirementsInput):RequirementsInput=>({...input,clarification:null})

const object=(value:unknown):value is Record<string,unknown>=>Boolean(value)&&typeof value==='object'&&!Array.isArray(value)
function keys(value:unknown,allowed:string[]):asserts value is Record<string,unknown>{
  if(!object(value)||Object.keys(value).some(key=>!allowed.includes(key)))throw Error('invalid')
}
function rawValue(value:unknown,max=32):value is string|number {
  return typeof value==='string'&&value.length<=max||typeof value==='number'&&Number.isFinite(value)&&Math.abs(value)<=1e12
}
function cleanInput(value:unknown):RequirementsInput {
  keys(value,['text','clarification'])
  if(value.text!==null&&(typeof value.text!=='string'||value.text.length>2000))throw Error('invalid')
  if(value.clarification===null)return {text:value.text as string|null,clarification:null}
  const source=value.clarification
  keys(source,['sourceId','sourceRevision','answers','selected','schedulePatch'])
  if(typeof source.sourceId!=='string'||!source.sourceId.trim()||source.sourceId.length>128||
    !Number.isSafeInteger(source.sourceRevision)||Number(source.sourceRevision)<1)throw Error('invalid')
  const fields=draftFields.map(field=>field.key)
  keys(source.answers,fields);keys(source.selected,[...fields,'day_schedules'])
  const answers:DraftAnswers={}
  for(const field of draftFields){
    if(!(field.key in source.answers))continue
    const raw=source.answers[field.key],max=field.maxlength??(field.key==='city'?60:field.key==='query'?240:32)
    if(!rawValue(raw,max)||field.type!=='number'&&typeof raw!=='string')throw Error('invalid')
    answers[field.key]=raw
  }
  const selected:Partial<Record<DraftField,boolean>>={}
  for(const [key,raw] of Object.entries(source.selected)){
    if(typeof raw!=='boolean')throw Error('invalid')
    selected[key as DraftField]=raw
  }
  let schedulePatch:SchedulePatch|null=null
  if(source.schedulePatch!==null){
    const patch=source.schedulePatch
    keys(patch,['count','days']);keys(patch.days,['0','1','2'])
    if(patch.count!==undefined&&patch.count!==null&&(!Number.isInteger(patch.count)||Number(patch.count)<1||Number(patch.count)>3))throw Error('invalid')
    if(patch.count===null&&Object.keys(patch.days).length)throw Error('invalid')
    const days:SchedulePatch['days']={}
    for(const [index,raw] of Object.entries(patch.days)){
      if(typeof patch.count==='number'&&Number(index)>=patch.count)throw Error('invalid')
      keys(raw,['day_start','day_end','stay_minutes'])
      const day:Partial<DraftDayInput>={}
      for(const key of ['day_start','day_end'] as const)if(key in raw){
        if(typeof raw[key]!=='string'||raw[key].length>5)throw Error('invalid')
        day[key]=raw[key]
      }
      if('stay_minutes' in raw){if(raw.stay_minutes!==null&&!rawValue(raw.stay_minutes))throw Error('invalid');day.stay_minutes=raw.stay_minutes as string|number|null}
      days[index]=day
    }
    schedulePatch={days,...('count' in patch?{count:patch.count as number|null}:{})}
  }
  return compact({text:value.text as string|null,clarification:{sourceId:source.sourceId,sourceRevision:Number(source.sourceRevision),answers,selected,schedulePatch}})
}
export function parseRequirementsInput(raw:string,now=Date.now()):StoredRequirementsInput {
  if(new TextEncoder().encode(raw).byteLength>MAX_SIZE)throw Error('本机需求输入超过 32 KiB，无法恢复；请放弃本机副本后重新填写。')
  try{
    const saved:unknown=JSON.parse(raw);keys(saved,['version','input','updatedAt'])
    if(saved.version!==1||typeof saved.updatedAt!=='number'||!Number.isFinite(saved.updatedAt)||saved.updatedAt>now+60_000)throw Error('invalid')
    if(now-saved.updatedAt>MAX_AGE)throw Error('expired')
    return {version:1,input:cleanInput(saved.input),updatedAt:saved.updatedAt}
  }catch(error){throw Error(error instanceof Error&&error.message==='expired'?'本机需求输入已超过 7 天，请放弃后重新填写。':'本机需求输入格式无效，无法恢复；请放弃本机副本后重新填写。')}
}
export class RequirementsInputConflict extends Error {
  constructor(){super('本机需求输入已在其他页面变化；请先核对最新副本，避免覆盖。')}
}
/** One sparse input per owner. Reading never restores, submits or overwrites it. */
export class RequirementsInputStore {
  draft:StoredRequirementsInput|null=null
  issue=''
  unavailable=false
  private expected:string|null=null
  constructor(private owner:string){
    try{this.expected=localStorage.getItem(requirementsInputKey(owner))}
    catch{this.unavailable=true;this.issue='浏览器无法读取本机需求输入；请保持页面打开，仍可手动提交。';return}
    try{if(this.expected)this.draft=parseRequirementsInput(this.expected)}
    catch(error){this.issue=error instanceof Error?error.message:'本机存储不可用'}
  }
  check(){if(localStorage.getItem(requirementsInputKey(this.owner))!==this.expected)throw new RequirementsInputConflict()}
  write(value:StoredRequirementsInput){
    this.check()
    const clean=parseRequirementsInput(JSON.stringify(value)),raw=JSON.stringify(clean)
    localStorage.setItem(requirementsInputKey(this.owner),raw)
    this.expected=raw;this.draft=clean;this.issue='';this.unavailable=false
  }
  clear(){this.check();localStorage.removeItem(requirementsInputKey(this.owner));this.expected=null;this.draft=null;this.issue=''}
}
