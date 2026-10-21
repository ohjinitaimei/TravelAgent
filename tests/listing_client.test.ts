import assert from 'node:assert/strict'
import test from 'node:test'
import { TravelApiError, TravelClient, fetchTransport } from '../packages/api-schema/client'

test('listing client keeps legacy URL and encodes generated query options with cancellation',async()=>{
  const calls:{path:string;signal?:AbortSignal}[]=[]
  const api=new TravelClient(async(path,init)=>{calls.push({path,signal:init?.signal});return {items:[]}})
  const legacy=await api.itineraries();assert.deepEqual(legacy,{items:[]});assert.equal(calls[0].path,'/itineraries')
  const controller=new AbortController()
  await api.itineraries({query:'TEST ONLY 城市 & %_',kind:'adjusted',order:'departure',parent_id:'TEST ONLY / parent',cursor:'opaque +/?=',limit:7},controller.signal)
  const url=new URL(calls[1].path,'http://test.invalid')
  assert.equal(url.searchParams.get('query'),'TEST ONLY 城市 & %_')
  assert.equal(url.searchParams.get('parent_id'),'TEST ONLY / parent')
  assert.equal(url.searchParams.get('cursor'),'opaque +/?=')
  assert.equal(url.searchParams.get('kind'),'adjusted');assert.equal(url.searchParams.get('order'),'departure')
  assert.equal(url.searchParams.get('limit'),'7');assert.equal(calls[1].signal,controller.signal)
})

test('actual HTTP listing metadata and invalid cursors use the shared typed error contract',async()=>{
  const api=new TravelClient(fetchTransport(process.env.TRAVEL_TEST_URL||'http://127.0.0.1:8000/api/v1/travel'))
  const result=await api.itineraries({query:'TEST ONLY %_',kind:'original',order:'oldest',limit:1})
  assert.equal(result.total,0);assert.deepEqual(result.items,[])
  assert.ok(result.page_cursor);assert.equal(result.next_cursor,null);assert.deepEqual(result.direct_adjustment_counts,{})
  await assert.rejects(()=>api.itineraries({cursor:'@invalid'}),error=>error instanceof TravelApiError&&error.code==='invalid_itinerary_cursor'&&!error.retryable)
})
