import assert from 'node:assert/strict'
import test from 'node:test'
import { TravelClient, type Itinerary } from '../packages/api-schema/client'
import { dayTransport } from '../apps/web/src/journey'
import { travelLimits, editSnapshot, editChanges } from '../apps/web/src/editor'
import { parseEditDraft } from '../apps/web/src/editDraft'
import { versionChanges, versionMetrics } from '../apps/web/src/versions'
import { restoreForm } from '../apps/web/src/session'

const source={provider:'user_input' as const,retrieved_at:'2026-10-22T00:00:00Z',coordinate_system:'GCJ-02' as const}
const poi=(id:string)=>({id,name:'TEST ONLY '+id,longitude:120,latitude:30,source})
const leg=(a:string,b:string,n:number)=>({origin_id:a,destination_id:b,duration_min:n,distance_km:n/10,mode:'walking' as const,polyline:[{longitude:120,latitude:30}],source})
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
