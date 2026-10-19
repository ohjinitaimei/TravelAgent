import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'node:http'
import { TravelApiError, TravelClient, fetchTransport } from '../packages/api-schema/client'
import { restoreForm } from '../apps/web/src/session'
import { userPrices } from '../apps/web/src/editor'
import { clarificationRequest, draftForm } from '../apps/web/src/draft'
import type { Draft } from '../packages/api-schema/client'
import { newSubmission, restoreSubmission, sendSubmission, recoverSubmission } from '../apps/web/src/submissions'
import { reactive } from 'vue'

test('polling cancels an in-flight request and enforces its deadline', async () => {
  const server = createServer((_request,_response)=>{})
  await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
  const address=server.address()
  assert.ok(address && typeof address!=='string')
  const api=new TravelClient(fetchTransport(`http://127.0.0.1:${address.port}`,5_000))
  try {
    const controller=new AbortController()
    const pending=api.wait('test-only',()=>assert.fail('No update after abort'),{signal:controller.signal})
    setTimeout(()=>controller.abort(),30)
    await assert.rejects(pending,(e:unknown)=>e instanceof Error && e.name==='AbortError')
    await assert.rejects(()=>api.wait('test-only',()=>{}, {timeoutMs:30}), (e:unknown)=>e instanceof TravelApiError&&e.code==='client_wait_timeout')
    await assert.rejects(()=>new TravelClient(fetchTransport(`http://127.0.0.1:${address.port}`,30)).task('test-only'),(e:unknown)=>e instanceof TravelApiError&&e.code==='request_timeout')
  } finally {server.closeAllConnections(); await new Promise<void>(resolve=>server.close(()=>resolve()))}
})

test('restoring user form discards invalid settings and provider data',()=>{
  const defaults={city:'',query:'',start_date:'2026-10-10',stay_minutes:60,mode:'walking' as const,user_prices:{}}
  const restored=restoreForm(defaults,{city:'北京',query:'公园',days:99,stay_minutes:-1,mode:'flight',budget:'unknown',user_prices:{unauthorized:500},start_date:'2026-10-12'})
  assert.equal(restored.city,'北京')
  assert.equal(restored.stay_minutes,60)
  assert.equal(restored.mode,'walking')
  assert.equal(restored.days,undefined)
  assert.deepEqual(restored.user_prices,{})
})

test('editor handles Vue numeric costs, preserves explicit zero and omits unknown or removed stops',()=>{
  assert.deepEqual(userPrices(['a','b','c','d'],{a:88,b:0,c:' ',d:'32.5',removed:100}),{a:88,b:0,d:32.5})
  assert.throws(()=>userPrices(['a'],{a:-1}),/费用/)
  assert.throws(()=>userPrices(['a'],{a:'NaN'}),/费用/)
})

test('applying a draft leaves required omissions blank and uses visible defaults',()=>{
  const draft={id:'test-only',created_at:'2026-10-11',input:{text:'预算0元',reference_date:'2026-10-11'},source:'helloagents',proposal:{values:{city:null,query:null,start_date:null,budget:0},evidence:{budget:'预算0元'}},questions:[],warnings:[],coordinator_action:'ask_clarification'} as Draft
  const form=draftForm(draft)
  assert.equal(form.city,'')
  assert.equal(form.start_date,'')
  assert.equal(form.budget,0)
  assert.equal(form.days,2)
  assert.deepEqual(form.user_prices,{})
})

test('clarification sends selected changes, preserves zero and confirms existing evidence',async()=>{
  const draft={id:'test-only/id',revision:2,confirmed_fields:['query'],proposal:{values:{city:'杭州',query:'博物馆',budget:800},evidence:{}}} as Draft
  const body=clarificationRequest(draft,{city:'杭州',query:'咖啡',budget:'0'},{city:true,budget:true})
  assert.deepEqual(body,{expected_revision:2,values:{budget:0},confirm_fields:['city','budget']})
  assert.deepEqual(clarificationRequest(draft,{city:''},{city:true}).values,{city:null})
  assert.deepEqual(clarificationRequest(draft,{budget:0},{budget:true}).values,{budget:0})
  assert.throws(()=>clarificationRequest(draft,{days:'1.5'},{days:true}),/范围/)
  assert.throws(()=>clarificationRequest(draft,{budget:'NaN'},{budget:true}),/范围/)
  assert.throws(()=>clarificationRequest(draft,{query:'博物馆'},{query:true}),/请选择/)
  const api=new TravelClient(async(path,init)=>{assert.equal(path,'/drafts/test-only%2Fid');assert.equal(init?.method,'PATCH');assert.deepEqual(init?.body,body);return draft})
  assert.equal((await api.clarifyDraft(draft.id,body)).id,draft.id)
})

test('polling reconnects with bounded backoff and does not restart the task',async()=>{
  let failures=2,posts=0,reads=0
  const states:string[]=[]
  const task={id:'test-only',status:'succeeded',kind:'plan',itinerary_id:'test-trip'}
  const api=new TravelClient(async(path,init)=>{
    if(init?.method==='POST') posts++
    if(path.endsWith('/events?after=0')) throw new TravelApiError('network_error','TEST ONLY',true)
    reads++
    if(failures-->0) throw new TravelApiError('network_error','TEST ONLY',true)
    return task
  })
  assert.equal((await api.wait(task.id,()=>{}, {retryDelayMs:1,onConnection:state=>states.push(state)})).status,'succeeded')
  assert.equal(reads,3)
  assert.equal(posts,0)
  assert.deepEqual(states,['reconnecting','reconnecting','connected'])
  failures=99
  await assert.rejects(()=>api.wait(task.id,()=>{}, {retryDelayMs:1,maxConsecutiveErrors:1}),(error:unknown)=>error instanceof TravelApiError&&error.code==='network_error')
  const missing=new TravelClient(async()=>{throw new TravelApiError('task_not_found','TEST ONLY',false)})
  await assert.rejects(()=>missing.wait('missing',()=>{}),(error:unknown)=>error instanceof TravelApiError&&error.code==='task_not_found')
})

test('a lost POST response is recovered by receipt with no duplicate submission',async()=>{
  let posts=0
  const task={id:'test-only-task',status:'queued',kind:'plan'}
  const api=new TravelClient(async(path,init)=>{
    if(init?.method==='POST') {posts++;assert.equal(init.headers?.['Idempotency-Key'],'test-only-key');throw new TravelApiError('network_error','TEST ONLY',true)}
    assert.equal(path,'/submissions/test-only-key');return task
  })
  const request=reactive({city:'TEST ONLY',query:'TEST ONLY',start_date:'2026-10-20',user_prices:{}})
  const pending=newSubmission({kind:'plan',request},'test-only-key')
  request.city='CHANGED AFTER SUBMIT'
  assert.equal(pending.operation.kind==='plan'&&pending.operation.request.city,'TEST ONLY')
  await assert.rejects(()=>sendSubmission(api,pending),/TEST ONLY/)
  assert.equal((await recoverSubmission(api,pending))?.id,task.id)
  assert.equal(posts,1)
  assert.equal(restoreSubmission({key:'bad',operation:{kind:'shell'}}),null)
  let sent=0
  const notAccepted=new TravelClient(async(_path,init)=>{if(init?.method==='POST'){sent++;return task}throw new TravelApiError('submission_not_found','TEST ONLY')})
  assert.equal(await recoverSubmission(notAccepted,pending,true),null)
  assert.equal(sent,0)
  assert.equal((await recoverSubmission(notAccepted,pending))?.id,task.id)
  assert.equal(sent,1)
})
