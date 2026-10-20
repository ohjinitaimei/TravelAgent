import assert from 'node:assert/strict'
import test from 'node:test'
import { EditDraftStore, EditDraftConflict, editDraftKey, parseEditDraft, itineraryBaseline, verifyEditSource, type EditDraft } from '../apps/web/src/editDraft'
import { editSnapshot } from '../apps/web/src/editor'
import { clearSession } from '../apps/web/src/session'
import type { Itinerary } from '../packages/api-schema/client'

function draft():EditDraft {
  const value=editSnapshot({groups:[['b','a'],['c']],prices:{a:'',b:0,c:-1},durations:{a:90,b:'',c:'NaN'},constraints:{start_date:'',day_start:'09:00',day_end:'18:00',mode:'walking',budget:''},defaultStay:60,optimize:false})
  return {version:1,sourceId:'TEST-ONLY-trip',sourceCreatedAt:'TEST ONLY timestamp',baseline:value,value,day:1,updatedAt:Date.now()}
}
function storage(run:(entries:Map<string,string>)=>void) {
  const previous=Object.getOwnPropertyDescriptor(globalThis,'localStorage'),entries=new Map<string,string>()
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:(k:string)=>entries.get(k)??null,setItem:(k:string,v:string)=>{entries.set(k,v)},removeItem:(k:string)=>entries.delete(k)}})
  try {run(entries)}finally{if(previous)Object.defineProperty(globalThis,'localStorage',previous);else Reflect.deleteProperty(globalThis,'localStorage')}
}
test('editor draft whitelist preserves partial user input and unknown versus zero without provider facts',()=>{
  const value=draft(),raw=JSON.stringify({...value,token:'TEST ONLY forbidden',poi:{name:'TEST ONLY forbidden'},value:{...value.value,providerFacts:{rating:5}}})
  const clean=parseEditDraft(raw)
  assert.deepEqual(clean,value)
  assert.equal(clean.value.prices.a,null);assert.equal(clean.value.prices.b,0)
  assert.equal(clean.value.durations.b,null);assert.equal(clean.value.durations.c,'NaN')
  assert.ok(!JSON.stringify(clean).includes('forbidden'));assert.ok(!JSON.stringify(clean).includes('providerFacts'))
})
test('editor draft rejects expired, future, duplicate, oversized and malformed storage',()=>{
  const value=draft(),now=Date.now()
  for(const bad of [{...value,updatedAt:now-8*86400000},{...value,updatedAt:now+120000},{...value,day:99},{...value,version:2},{...value,value:{...value.value,groups:[['a','a'],[]]}}])assert.throws(()=>parseEditDraft(JSON.stringify(bad),now))
  assert.throws(()=>parseEditDraft('bad JSON'));assert.throws(()=>parseEditDraft(' '.repeat(32769)))
})
test('editor restoration verifies immutable source and editable baseline independently of provider facts',()=>{
  const trip={id:'TEST-ONLY-trip',created_at:'TEST ONLY timestamp',request:{start_date:'2026-10-20',day_start:'09:00',day_end:'18:00',mode:'walking',stay_minutes:60},days:[{stops:[{poi:{id:'b',name:'TEST ONLY'},stay_minutes:60,user_cost:null},{poi:{id:'a'},stay_minutes:90,user_cost:0}]}]} as Itinerary
  const value={...draft(),baseline:itineraryBaseline(trip)}
  verifyEditSource(value,trip)
  verifyEditSource(parseEditDraft(JSON.stringify({...value,value:value.baseline,day:0})),trip)
  for(const changed of [{...trip,id:'other'},{...trip,created_at:'new'},{...trip,request:{...trip.request,day_end:'17:00'}}])assert.throws(()=>verifyEditSource(value,changed))
})
test('editor storage isolates owners and rejects stale tab writes and deletion',()=>storage(entries=>{
  const first=new EditDraftStore('alpha'),stale=new EditDraftStore('alpha'),beta=new EditDraftStore('beta')
  first.write(draft());beta.write({...draft(),sourceId:'beta'})
  assert.throws(()=>stale.write(draft()),EditDraftConflict);assert.throws(()=>stale.clear(),EditDraftConflict)
  assert.equal(new EditDraftStore('alpha').draft?.sourceId,'TEST-ONLY-trip')
  assert.equal(entries.size,2)
  clearSession('alpha');assert.equal(entries.has(editDraftKey('alpha')),false);assert.ok(entries.has(editDraftKey('beta')))
}))
test('storage failure leaves the last durable draft intact and allows retry',()=>storage(entries=>{
  const store=new EditDraftStore('alpha');store.write(draft())
  const before=entries.get(editDraftKey('alpha')),set=localStorage.setItem
  localStorage.setItem=()=>{throw Error('TEST ONLY quota')}
  assert.throws(()=>store.write({...draft(),day:0}));assert.equal(entries.get(editDraftKey('alpha')),before)
  localStorage.setItem=set;store.write({...draft(),day:0});assert.equal(new EditDraftStore('alpha').draft?.day,0)
}))
test('malformed or expired drafts remain available for explicit discard without silent replacement',()=>storage(entries=>{
  entries.set(editDraftKey('alpha'),'{bad')
  const store=new EditDraftStore('alpha');assert.equal(store.draft,null);assert.match(store.issue,/格式无效/)
  assert.equal(entries.get(editDraftKey('alpha')),'{bad');store.clear();assert.equal(entries.size,0)
  const get=localStorage.getItem
  localStorage.getItem=()=>{throw Error('TEST ONLY storage denied')}
  const unavailable=new EditDraftStore('beta');assert.equal(unavailable.unavailable,true);assert.match(unavailable.issue,/仍可编辑/)
  localStorage.getItem=get
  unavailable.write(draft());assert.equal(unavailable.unavailable,false);unavailable.clear();assert.equal(entries.has(editDraftKey('beta')),false)
}))
