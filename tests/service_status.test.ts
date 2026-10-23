import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ServiceMonitor, intakeStatus, serviceSummary } from '../apps/web/src/serviceStatus'
import type { Schema } from '../packages/api-schema/client'

const capability:Schema<'Capabilities'>={configured:true,provider:'amap',tool_transport:'direct',draft_enabled:true,helloagents_available:true,llm_configured:true,limitations:[]}
function deferred<T>(){let resolve!:(value:T)=>void,reject!:(error:unknown)=>void;const promise=new Promise<T>((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}

test('unknown and failed connection never claim a missing credential, and a manual read can recover',async()=>{
  let calls=0
  const monitor=new ServiceMonitor(async()=>{if(++calls===1)throw Error('TEST ONLY private upstream message');return capability},()=>{},()=> '2026-10-23T00:00:00Z')
  assert.equal(serviceSummary(monitor.state),'正在读取服务状态')
  await monitor.refresh()
  assert.equal(serviceSummary(monitor.state),'服务状态未读取')
  assert.equal(monitor.state.capability,null)
  assert.equal(monitor.state.checkedAt,null)
  assert.ok(!monitor.state.error.includes('private'))
  await monitor.refresh()
  assert.equal(serviceSummary(monitor.state),'地图数据授权已配置')
  assert.equal(monitor.state.checkedAt,'2026-10-23T00:00:00Z')
  assert.equal(calls,2)
})

test('a failed refresh retains the last snapshot and time without claiming it is current',async()=>{
  let fail=false
  const monitor=new ServiceMonitor(async()=>{if(fail)throw Error('TEST ONLY');return capability},()=>{},()=> '2026-10-23T00:00:00Z')
  await monitor.refresh();fail=true
  await monitor.refresh()
  assert.equal(monitor.state.phase,'stale')
  assert.equal(serviceSummary(monitor.state),'服务状态需刷新')
  assert.equal(monitor.state.capability,capability)
  assert.equal(monitor.state.checkedAt,'2026-10-23T00:00:00Z')
  assert.equal(intakeStatus(monitor.state.capability,false).enabled,false)
})

test('refresh is single-flight, and an old pre-offline response cannot replace newer state',async()=>{
  const old=deferred<Schema<'Capabilities'>>(),fresh=deferred<Schema<'Capabilities'>>()
  let calls=0
  const monitor=new ServiceMonitor(()=>++calls===1?old.promise:fresh.promise,()=>{})
  const first=monitor.refresh()
  assert.equal(monitor.refresh(),first)
  await Promise.resolve();assert.equal(calls,1)
  monitor.offline()
  const second=monitor.refresh()
  await Promise.resolve();assert.equal(calls,2)
  fresh.resolve({...capability,configured:false});await second
  assert.equal(monitor.state.capability?.configured,false)
  old.resolve(capability);await first
  assert.equal(monitor.state.capability?.configured,false)
  assert.equal(monitor.state.phase,'ready')
})

test('disposing an account workspace ignores delayed reads and prevents further calls',async()=>{
  const read=deferred<Schema<'Capabilities'>>()
  let calls=0,updates=0
  const monitor=new ServiceMonitor(()=>{calls++;return read.promise},()=>updates++)
  const work=monitor.refresh();await Promise.resolve()
  monitor.dispose();read.resolve(capability);await work;await monitor.refresh();monitor.offline()
  assert.equal(calls,1);assert.equal(updates,1);assert.equal(monitor.state.capability,null)
})

test('intake availability distinguishes optional prerequisites and requires a current snapshot',()=>{
  assert.equal(intakeStatus(null,true).enabled,false)
  assert.equal(intakeStatus(capability,false).label,'需求整理状态待确认')
  assert.equal(intakeStatus({...capability,draft_enabled:false},true).label,'需求整理未启用')
  assert.equal(intakeStatus({...capability,helloagents_available:false},true).label,'需求整理依赖未就绪')
  assert.equal(intakeStatus({...capability,llm_configured:false},true).label,'模型服务配置不完整')
  assert.equal(intakeStatus(capability,true).enabled,true)
})
