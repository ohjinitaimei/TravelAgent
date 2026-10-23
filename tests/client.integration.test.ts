import assert from 'node:assert/strict'
import test from 'node:test'
import { TravelApiError, TravelClient, fetchTransport } from '../packages/api-schema/client'

const base = process.env.TRAVEL_TEST_URL || 'http://127.0.0.1:8000/api/v1/travel'
const api = new TravelClient(fetchTransport(base))

test('actual HTTP: direct tool check is independent of provider authorization', async () => {
  const result=await api.checkToolService()
  assert.equal(result.transport,'direct')
  assert.equal(result.mcp_state,'available')
  assert.equal(result.provider_configured,false)
  assert.deepEqual(new Set(result.tools),new Set(['search_pois','get_poi','get_route']))
  assert.equal(result.error,null)
})

test('actual HTTP: shared client observes real fail-closed task, SSE and validation', async () => {
  const capability = await api.capabilities()
  if (capability.configured) throw new Error('This test expects an unconfigured provider; never spend real API quota in this negative-path test')
  const created = await api.create({city:'北京', query:'博物馆', start_date:'2026-10-10', days:1, stops_per_day:2, user_prices:{}})
  assert.equal(created.status, 'queued')
  const stages: string[] = []
  const final = await api.wait(created.id, (_, events)=>stages.push(...events.map(e=>e.stage)), {intervalMs:100})
  assert.equal(final.status, 'failed')
  assert.equal(final.error?.code, 'provider_not_configured')
  assert.equal(final.itinerary_id, null)
  assert.ok(stages.includes('search'))
  const stream = await fetch(`${base}/tasks/${created.id}/events/stream`)
  const sse = await stream.text()
  assert.match(sse, /event: terminal/)
  assert.match(sse, /provider_not_configured/)
  await assert.rejects(()=>api.create({city:'',query:'',start_date:'2026-10-10'}), (e:unknown)=>e instanceof TravelApiError && e.code==='validation_error')
  await assert.rejects(()=>api.search('博物馆','北京'), (e:unknown)=>e instanceof TravelApiError && e.code==='provider_not_configured')
  const cancel = await api.create({city:'北京', query:'博物馆', start_date:'2026-10-10'})
  const cancelled = await api.cancel(cancel.id)
  assert.equal(cancelled.status, 'cancelled')
})

test('actual HTTP: disabled intake is a typed asynchronous failure, without an itinerary',async()=>{
  const capability=await api.capabilities()
  if(capability.draft_enabled) throw new Error('Negative path must not contact a real model')
  const created=await api.createDraft({text:'去杭州逛博物馆',reference_date:'2026-10-11'})
  assert.equal(created.kind,'draft')
  const final=await api.wait(created.id,()=>{}, {intervalMs:100})
  assert.equal(final.status,'failed')
  assert.equal(final.error?.code,'agent_disabled')
  assert.equal(final.draft_id,null)
  assert.equal(final.itinerary_id,null)
})
