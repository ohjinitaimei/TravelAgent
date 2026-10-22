import { scheduleAt, sharedScheduleReady, cloneSchedules, parseScheduleInputs, validatedSchedules } from '../apps/web/src/schedules'
import assert from 'node:assert/strict'
import test from 'node:test'
import { TravelClient, type Itinerary } from '../packages/api-schema/client'
import { dayTransport } from '../apps/web/src/journey'
import { travelLimits, editSnapshot, editChanges } from '../apps/web/src/editor'
import { parseEditDraft } from '../apps/web/src/editDraft'
import { versionChanges, versionMetrics } from '../apps/web/src/versions'
import { restoreForm } from '../apps/web/src/session'
import { endpointAt, parseEndpoints, selectedAnchorIds } from '../apps/web/src/endpoints'
import { draftForm } from '../apps/web/src/draft'
import type { Draft } from '../apps/web/src/api'

const source={provider:'user_input' as const,retrieved_at:'2026-10-22T00:00:00Z',coordinate_system:'GCJ-02' as const}
const poi=(id:string)=>({id,name:'TEST ONLY '+id,longitude:120,latitude:30,source})
const leg=(a:string,b:string,n:number)=>({origin_id:a,destination_id:b,duration_min:n,distance_km:n/10,mode:'walking' as const,polyline:[{longitude:120,latitude:30}],source})

test('individual endpoints resolve by date and saved totals reject mismatched daily facts',()=>{
  const value=trip()
  value.request.days=2;value.request.day_origin_poi_id=null;value.request.day_destination_poi_id=null
  value.request.day_endpoints=[{origin_poi_id:'home',destination_poi_id:'hotel'},{origin_poi_id:null,destination_poi_id:'hotel-2'}]
  const second=structuredClone(value.days[0]);second.date='2026-10-24';second.origin_poi=null;second.origin_segment=null
  second.destination_poi=poi('hotel-2');second.destination_segment=leg('a','hotel-2',9)
  value.days.push(second)
  assert.equal(dayTransport(second,value.request).total,9)
  assert.equal(versionMetrics(value).travel,39)
  second.destination_poi=poi('hotel')
  assert.equal(dayTransport(second,value.request).total,null)
  assert.equal(versionMetrics(value).travel,null)
})

test('daily edits and version differences show only the affected date with saved names',()=>{
  const parent=trip();parent.request.day_origin_poi_id=null;parent.request.day_destination_poi_id=null
  parent.request.day_endpoints=[{origin_poi_id:'home',destination_poi_id:'hotel'}]
  const child=structuredClone(parent);child.id='child';child.parent_id=parent.id
  child.request.day_endpoints![0].destination_poi_id=null;child.days[0].destination_poi=null;child.days[0].destination_segment=null
  const changes=versionChanges(parent,child)
  assert.ok(changes.some(change=>change.label==='第 1 天返回地'&&change.before==='TEST ONLY hotel'&&change.after==='未设置'))
  assert.equal(parent.request.day_endpoints![0].destination_poi_id,'hotel')
})

test('daily drafts normalize old input and reject count conflicts or embedded provider facts',()=>{
  const value=trip(),baseline=editSnapshot({groups:[['a']],prices:{},durations:{a:60},constraints:{...value.request,day_origin_poi_id:null,day_destination_poi_id:null},defaultStay:60,optimize:false})
  const old={...baseline};delete (old as Partial<typeof old>).day_endpoints
  const input={version:1,sourceId:'TEST ONLY',sourceCreatedAt:'',baseline:old,value:{...baseline,day_endpoints:[{origin_poi_id:'home',destination_poi_id:null}]},day:0,updatedAt:Date.now()}
  const draft=parseEditDraft(JSON.stringify(input))
  assert.equal(draft.baseline.day_endpoints,null);assert.equal(draft.value.day_endpoints?.[0].origin_poi_id,'home')
  assert.throws(()=>parseEditDraft(JSON.stringify({...input,value:{...input.value,day_origin_poi_id:'mixed'}})))
  for(const raw of [[],[{},{}],[{origin_poi_id:' '}],[{origin_poi_id:'home',longitude:120}]])assert.throws(()=>parseEndpoints(raw,1))
})

test('workspace restoration validates daily IDs and applying natural drafts clears prior daily choices',()=>{
  const defaults={...trip().request,day_origin_poi_id:null,day_destination_poi_id:null}
  const daily=[{origin_poi_id:'home',destination_poi_id:null}]
  const restored=restoreForm(defaults,{...defaults,day_endpoints:daily})
  assert.deepEqual(restored.day_endpoints,daily)
  assert.deepEqual(selectedAnchorIds(restored),['home'])
  assert.equal(endpointAt(restored,1),undefined)
  assert.equal(draftForm({proposal:{values:{city:'TEST ONLY'}}} as Draft).day_endpoints,null)
  assert.equal(restoreForm(defaults,{...defaults,day_endpoints:[{origin_poi_id:'home',source:{provider:'amap'}}]}).day_endpoints,undefined)
})
function trip():Itinerary{return {id:'root',title:'TEST ONLY',request:{city:'TEST ONLY',query:'TEST ONLY',days:1,stops_per_day:1,start_date:'2026-10-23',day_start:'09:00',day_end:'18:00',stay_minutes:60,mode:'walking',day_origin_poi_id:'home',day_destination_poi_id:'hotel'},days:[{date:'2026-10-23',origin_poi:poi('home'),destination_poi:poi('hotel'),origin_segment:leg('home','a',10),destination_segment:leg('a','hotel',20),origin_departure_time:'09:00',return_arrival_time:'10:30',stops:[{poi:poi('a'),stay_minutes:60,arrival_time:'09:10',departure_time:'10:10',travel_to_next:null}]}],budget:{known_subtotal:0,total:null,unknown_items:['TEST ONLY'],status:'unknown'},warnings:[]}}

test('saved totals include both boundaries and keep missing necessary transport unknown',()=>{
  const value=trip(),before=structuredClone(value),metrics=versionMetrics(value)
  assert.equal(metrics.travel,30);assert.equal(metrics.interstopTravel,0);assert.equal(metrics.boundaryTravel,30)
  assert.equal(metrics.distance,3);assert.deepEqual(value,before)
  value.days[0].destination_segment=null
  assert.equal(dayTransport(value.days[0],value.request).total,null)
  value.days[0].destination_poi=poi('a');value.request.day_destination_poi_id='a'
  assert.equal(dayTransport(value.days[0],value.request).total,10)
})

test('endpoint differences use saved names and never change source versions',()=>{
  const parent=trip(),child=structuredClone(parent)
  child.id='child';child.parent_id=parent.id;child.request.day_destination_poi_id=null
  child.days[0].destination_poi=null;child.days[0].destination_segment=null;child.days[0].return_arrival_time=null
  assert.ok(versionChanges(parent,child).some(c=>c.label==='返回地'&&c.before==='TEST ONLY hotel'&&c.after==='未设置'))
  assert.equal(parent.days[0].destination_poi?.id,'hotel')
})

test('old v1 drafts normalize absent endpoints while new drafts persist only selected IDs',()=>{
  const old=editSnapshot({groups:[['a']],prices:{a:null},durations:{a:60},constraints:{start_date:'2026-10-23',day_start:'09:00',day_end:'18:00',mode:'walking',budget:null},defaultStay:60,optimize:false})
  const input={version:1,sourceId:'TEST ONLY',sourceCreatedAt:'',baseline:{...old},value:{...old},day:0,updatedAt:Date.now()}
  delete (input.baseline as Partial<typeof old>).day_origin_poi_id
  delete (input.baseline as Partial<typeof old>).day_destination_poi_id
  input.value.day_origin_poi_id='home'
  const restored=parseEditDraft(JSON.stringify(input))
  assert.equal(restored.baseline.day_origin_poi_id,null);assert.equal(restored.value.day_origin_poi_id,'home')
  assert.ok(editChanges(restored.baseline,restored.value,id=>id).some(c=>c.label==='出发地'))
  assert.throws(()=>parseEditDraft(JSON.stringify({...input,value:{...input.value,day_origin_poi_id:' '.repeat(3)}})))
  const multiday={...input,baseline:{...old,groups:[['a'],['b']],prices:{a:null,b:null},durations:{a:60,b:60}},value:{...input.value,groups:[['a'],['b']],prices:{a:null,b:null},durations:{a:60,b:60}}}
  assert.equal(parseEditDraft(JSON.stringify(multiday)).value.day_origin_poi_id,'home')
})

test('restored planner and requests retain endpoints and forward search cancellation',async()=>{
  const value=trip().request
  assert.equal(restoreForm(value,{...value,day_origin_poi_id:null}).day_origin_poi_id,null)
  const controller=new AbortController(),calls:{path:string;init:any}[]=[]
  const api=new TravelClient(async(path,init)=>{calls.push({path,init});return {items:[]}})
  await api.search('TEST ONLY a&b','TEST ONLY',controller.signal)
  await api.detail('TEST ONLY home',controller.signal)
  await api.create(value)
  assert.equal(calls[0].init.signal,controller.signal);assert.equal(calls[1].init.signal,controller.signal)
  assert.match(calls[0].path,/a%26b/);assert.equal(calls[2].init.body.day_origin_poi_id,'home')
})


test('travel limits normalize explicit clearing and reject fractional or coerced inputs',()=>{
  assert.deepEqual(travelLimits({max_leg_travel_minutes:'',max_daily_travel_minutes:null}),{max_leg_travel_minutes:null,max_daily_travel_minutes:null})
  assert.equal(travelLimits({max_leg_travel_minutes:1,max_daily_travel_minutes:1439}).max_daily_travel_minutes,1439)
  for(const value of [0,1440,1.2,'30',NaN])assert.throws(()=>travelLimits({max_leg_travel_minutes:value}))
})

test('travel limits persist as user inputs and old draft baselines normalize absent fields',()=>{
  const original=trip(),baseline=editSnapshot({groups:[['a']],prices:{a:null},durations:{a:60},constraints:original.request,defaultStay:60,optimize:false})
  const old={...baseline} as Partial<typeof baseline>;delete old.max_leg_travel_minutes;delete old.max_daily_travel_minutes
  const value={...baseline,max_leg_travel_minutes:20,max_daily_travel_minutes:45}
  const restored=parseEditDraft(JSON.stringify({version:1,sourceId:original.id,sourceCreatedAt:'',baseline:old,value,day:0,updatedAt:Date.now()}))
  assert.equal(restored.baseline.max_leg_travel_minutes,null)
  assert.equal(restored.value.max_daily_travel_minutes,45)
  assert.equal(restoreForm(original.request,{...original.request,max_leg_travel_minutes:20}).max_leg_travel_minutes,20)
  assert.equal(restoreForm(original.request,{...original.request,max_leg_travel_minutes:1.5}).max_leg_travel_minutes,undefined)
  assert.ok(editChanges(restored.baseline,restored.value,id=>id).some(c=>c.label==='单段交通上限'&&c.after==='20 分钟'))
  assert.ok(editChanges(restored.value,restored.baseline,id=>id).some(c=>c.label==='单段交通上限'&&c.after==='未设置'))
})


test('daily schedules validate complete same-day inputs with strict integer defaults',()=>{
  const daily=[{day_start:'08:00',day_end:'12:00',stay_minutes:30},{day_start:'14:00',day_end:'18:00',stay_minutes:45}]
  assert.deepEqual(validatedSchedules({day_schedules:daily},2).day_schedules,daily)
  assert.equal(scheduleAt({day_schedules:daily,stay_minutes:60},1)?.stay_minutes,45)
  assert.equal(scheduleAt({day_schedules:daily},2),undefined)
  assert.equal(validatedSchedules({},2).day_schedules,null)
  for(const stay of ['30',null,9,361,30.5,true])assert.throws(()=>validatedSchedules({day_schedules:[{...daily[0],stay_minutes:stay as number}]},1))
  for(const day of [{...daily[0],day_end:'07:00'},{...daily[0],day_start:''},{...daily[0],day_start:'8:00'}])assert.throws(()=>validatedSchedules({day_schedules:[day]},1))
  assert.throws(()=>parseScheduleInputs(daily,1))
  assert.throws(()=>parseScheduleInputs([{...daily[0],source:{provider:'amap'}}],1))
})

test('daily schedule drafts preserve incomplete inputs and normalize legacy absence',()=>{
  const value=trip(),baseline=editSnapshot({groups:[['a']],prices:{},durations:{a:60},constraints:value.request,defaultStay:60,optimize:false})
  const old={...baseline};delete (old as Partial<typeof old>).day_schedules
  const input={version:1,sourceId:'TEST ONLY',sourceCreatedAt:'',baseline:old,value:{...baseline,day_schedules:[{day_start:'',day_end:'08:00',stay_minutes:null}]},day:0,updatedAt:Date.now()}
  const result=parseEditDraft(JSON.stringify(input))
  assert.equal(result.baseline.day_schedules,null)
  assert.deepEqual(result.value.day_schedules,input.value.day_schedules)
  assert.throws(()=>validatedSchedules(result.value,1))
  assert.throws(()=>parseEditDraft(JSON.stringify({...input,value:{...input.value,day_schedules:[{...input.value.day_schedules[0],price:1}]}})))
  assert.throws(()=>parseEditDraft(JSON.stringify({...input,value:{...input.value,day_schedules:[]}})))
})

test('daily defaults do not override explicit stops and new stops use their target day',()=>{
  const constraints={...trip().request,day_schedules:[{day_start:'08:00',day_end:'12:00',stay_minutes:30},{day_start:'14:00',day_end:'18:00',stay_minutes:45}]}
  const original=editSnapshot({groups:[['a'],['b']],prices:{},durations:{a:60},constraints,defaultStay:90,optimize:false})
  assert.deepEqual(original.durations,{a:60,b:45})
  const moved=editSnapshot({groups:[['b'],['a']],prices:{},durations:original.durations,constraints,defaultStay:90,optimize:false})
  assert.deepEqual(moved.durations,original.durations)
  const copy=cloneSchedules(constraints.day_schedules)!
  copy[0].stay_minutes=120
  assert.equal(constraints.day_schedules[0].stay_minutes,30)
})

test('schedule and stop changes appear separately in edit and saved version comparisons',()=>{
  const parent=trip();parent.request.day_schedules=[{day_start:'08:00',day_end:'12:00',stay_minutes:30}]
  const child=structuredClone(parent);child.id='child';child.parent_id=parent.id
  child.request.day_schedules![0]={day_start:'10:00',day_end:'16:00',stay_minutes:45}
  const changes=versionChanges(parent,child)
  assert.ok(changes.some(c=>c.label==='第 1 天开始'&&c.after==='10:00'))
  assert.ok(changes.some(c=>c.label==='第 1 天默认停留'&&c.after==='45 分钟'))
  assert.ok(!changes.some(c=>c.label.startsWith('停留 ')))
  assert.equal(parent.request.day_schedules[0].day_start,'08:00')
  child.request.day_schedules=null
  assert.ok(versionChanges(parent,child).some(c=>c.label==='时段设置方式'&&c.after==='所有日期共用'))
})

test('workspace restores incomplete daily fields while rejecting injected facts',()=>{
  const defaults={...trip().request,day_schedules:null}
  const daily=[{day_start:'',day_end:'07:00',stay_minutes:''}]
  assert.deepEqual(restoreForm(defaults,{...defaults,day_schedules:daily}).day_schedules,[{...daily[0],stay_minutes:null}])
  assert.equal(restoreForm(defaults,{...defaults,day_schedules:[{...daily[0],longitude:120}]}).day_schedules,null)
  assert.equal(draftForm({proposal:{values:{city:'TEST ONLY'}}} as Draft).day_schedules,null)
})


test('mode switching requires complete shared fields so invalid fallback values remain editable',()=>{
  const valid={day_start:'09:00',day_end:'18:00',stay_minutes:60}
  assert.equal(sharedScheduleReady(valid),true)
  for(const input of [{...valid,day_start:''},{...valid,day_end:'08:00'},...['',null,'30',30.5,9,true].map(stay=>({...valid,stay_minutes:stay as number}))])assert.equal(sharedScheduleReady(input),false)
})
