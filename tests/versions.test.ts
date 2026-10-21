import assert from 'node:assert/strict'
import test from 'node:test'
import { directVersions, filterVersions, versionChanges, versionMetrics, versionTime, type VersionFilter } from '../apps/web/src/versions'
import type { Itinerary } from '../packages/api-schema/client'

// Explicit TEST ONLY snapshots. No provider, browser storage or production fallback.
function trip(id:string,parent:string|null=null,time='2026-10-21T01:00:00Z'):Itinerary {
  const source={provider:'user_input' as const,retrieved_at:time,coordinate_system:'GCJ-02' as const}
  return {id,parent_id:parent,created_at:time,title:'TEST ONLY 相同标题',request:{city:'TEST ONLY 城市',query:'TEST ONLY',start_date:'2026-10-22',days:1,stops_per_day:2,day_start:'09:00',day_end:'18:00',stay_minutes:60,mode:'walking'},
    days:[{date:'2026-10-22',stops:['a','b'].map((name,index)=>({poi:{id:name,name:'TEST ONLY '+name,longitude:120+index*.01,latitude:30,source},arrival_time:index?'10:37':'09:00',departure_time:index?'11:37':'10:00',stay_minutes:60,user_cost:null,travel_to_next:index?null:{origin_id:'a',destination_id:'b',mode:'walking',distance_km:12,duration_min:37,polyline:[{longitude:120,latitude:30}],source}}))}],budget:{known_subtotal:0,total:null,currency:'CNY',unknown_items:['TEST ONLY unknown'],status:'unknown'},warnings:[]}
}
const filter:VersionFilter={query:'',kind:'all',order:'newest',parentId:null}

test('version filters use actual parent edges and IDs, never shared title or date as lineage',()=>{
  const data=[trip('root-a'),trip('child','root-a'),trip('grandchild','child'),trip('unrelated')]
  assert.deepEqual(filterVersions(data,{...filter,kind:'original'}).map(t=>t.id),['root-a','unrelated'])
  assert.deepEqual(filterVersions(data,{...filter,parentId:'root-a'}).map(t=>t.id),['child'])
  assert.deepEqual(directVersions(data,'root-a').map(t=>t.id),['child'])
  assert.deepEqual(filterVersions(data,{...filter,query:' GRANDCHILD '}).map(t=>t.id),['grandchild'])
  assert.equal(filterVersions(data,{...filter,kind:'adjusted',query:'not present'}).length,0)
})

test('version sorting is deterministic, keeps missing time unknown and does not mutate source data',()=>{
  const old=trip('old',null,'2026-10-20T01:00:00Z'),recent=trip('recent',null,'2026-10-21T01:00:00Z'),unknown=trip('unknown')
  delete unknown.created_at
  recent.request.start_date='2026-10-23'
  const data=[unknown,old,recent],original=structuredClone(data)
  assert.deepEqual(filterVersions(data,filter).map(t=>t.id),['recent','old','unknown'])
  assert.deepEqual(filterVersions(data,{...filter,order:'oldest'}).map(t=>t.id),['old','recent','unknown'])
  assert.deepEqual(filterVersions(data,{...filter,order:'departure'}).map(t=>t.id),['old','unknown','recent'])
  assert.equal(versionTime(undefined),'保存时间未提供');assert.equal(versionTime('invalid'),'保存时间未提供')
  assert.deepEqual(data,original)
})

test('saved comparisons reuse input differences and preserve explicit zero versus unknown without edits',()=>{
  const parent=trip('root'),child=trip('child','root'),original=structuredClone(parent)
  child.days[0].stops[0].stay_minutes=90;child.days[0].stops[0].user_cost=0
  child.request.day_end='19:00'
  const changes=versionChanges(parent,child)
  assert.ok(changes.some(c=>c.label==='费用 TEST ONLY a'&&c.before==='未知'&&c.after==='0 元'))
  assert.ok(changes.some(c=>c.label==='停留 TEST ONLY a'&&c.before==='60 分钟'&&c.after==='90 分钟'))
  assert.ok(changes.some(c=>c.label==='每日结束'&&c.after==='19:00'))
  assert.equal(versionMetrics(parent).missingStationCosts,2)
  assert.equal(versionMetrics(child).missingStationCosts,1)
  assert.equal(versionMetrics(child).totalCost,null)
  assert.deepEqual(parent,original)
})

test('saved traffic summaries mark incomplete or mismatched routes unknown instead of zero',()=>{
  const value=trip('root')
  assert.equal(versionMetrics(value).travel,37)
  value.days[0].stops[0].travel_to_next=null
  assert.equal(versionMetrics(value).travel,null);assert.equal(versionMetrics(value).distance,null)
  const mismatch=trip('mismatch');mismatch.days[0].stops[0].travel_to_next!.destination_id='TEST ONLY wrong'
  assert.equal(versionMetrics(mismatch).travel,null)
  value.days[0].stops.pop()
  assert.equal(versionMetrics(value).travel,0)
})

test('comparison rejects a wrong parent response or a self-referential version',()=>{
  assert.throws(()=>versionChanges(trip('foreign'),trip('child','root')),/来源不匹配/)
  assert.throws(()=>versionChanges(trip('same'),trip('same','same')),/来源不匹配/)
})
