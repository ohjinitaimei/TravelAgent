/** TEST ONLY SDK lifecycle, with no browser key, network or map provider. */
import assert from 'node:assert/strict'
import test from 'node:test'
import { MapLoading, type MapStatus } from '../apps/web/src/mapLoading'

function deferred<T>() {
  let resolve!:(value:T)=>void,reject!:(error:unknown)=>void
  const promise=new Promise<T>((ok,fail)=>{resolve=ok;reject=fail})
  return {promise,resolve,reject}
}

test('first Map constructor failure is visible and only successful redraw can publish ready',async()=>{
  const states:MapStatus[]=[]
  let attempts=0,draws=0,destroyed=0,resets=0
  const lifecycle=new MapLoading({configured:true,load:async()=>({Map:class{constructor(){if(++attempts===1)throw Error('TEST ONLY draw rejected')}}}),
    reset:()=>{resets++},draw:sdk=>{new sdk.Map();draws++},destroy:()=>{destroyed++},status:value=>states.push(value)})
  await lifecycle.start()
  assert.equal(lifecycle.state,'error');assert.equal(states.includes('ready'),false)
  assert.equal(draws,0);assert.ok(destroyed>=2)
  await lifecycle.retry()
  assert.equal(lifecycle.state,'ready');assert.equal(draws,1);assert.equal(resets,0)
})

test('sticky SDK loading failure is reset only on explicit retry, never by props or another start',async()=>{
  let failed=false,loads=0,resets=0,draws=0
  const lifecycle=new MapLoading({configured:true,load:async()=>{loads++;if(!resets){failed=true;throw Error('TEST ONLY SDK load failed')}if(failed)throw Error('TEST ONLY sticky loader');return {}},
    reset:()=>{resets++;failed=false},draw:()=>{draws++},destroy:()=>{},status:()=>{}})
  await lifecycle.start();assert.equal(lifecycle.state,'error')
  lifecycle.redraw();await lifecycle.start()
  assert.equal(loads,1);assert.equal(resets,0);assert.equal(draws,0)
  await lifecycle.retry()
  assert.equal(loads,2);assert.equal(resets,1);assert.equal(draws,1);assert.equal(lifecycle.state,'ready')
})

test('repeated clicks do not start concurrent attempts and pending load draws the latest props',async()=>{
  const pending=deferred<object>(),drawn:number[]=[]
  let loads=0,day=0
  const lifecycle=new MapLoading({configured:true,load:()=>{loads++;return pending.promise},reset:()=>{},draw:()=>drawn.push(day),destroy:()=>{},status:()=>{}})
  const attempt=lifecycle.start()
  await lifecycle.start();await lifecycle.retry();lifecycle.redraw()
  assert.equal(loads,1);assert.deepEqual(drawn,[])
  day=2;pending.resolve({});await attempt
  assert.deepEqual(drawn,[2]);assert.equal(lifecycle.state,'ready')
  await lifecycle.retry();assert.equal(loads,1)
})

test('unmounted maps ignore a late successful SDK result and cannot be retried',async()=>{
  const pending=deferred<object>(),states:MapStatus[]=[]
  let loads=0,draws=0,destroys=0
  const lifecycle=new MapLoading({configured:true,load:()=>{loads++;return pending.promise},reset:()=>{},draw:()=>{draws++},destroy:()=>{destroys++},status:value=>states.push(value)})
  const attempt=lifecycle.start();lifecycle.dispose();const before=[...states]
  pending.resolve({});await attempt;await lifecycle.retry();lifecycle.redraw()
  assert.equal(loads,1);assert.equal(draws,0);assert.ok(destroys>=2);assert.deepEqual(states,before)
})

test('unmounted maps ignore a late SDK rejection without publishing an error or retrying',async()=>{
  const pending=deferred<object>(),states:MapStatus[]=[]
  const lifecycle=new MapLoading({configured:true,load:()=>pending.promise,reset:()=>assert.fail('No retry after unmount'),draw:()=>assert.fail('No drawing after unmount'),destroy:()=>{},status:value=>states.push(value)})
  const attempt=lifecycle.start();lifecycle.dispose();const before=[...states]
  pending.reject(Error('TEST ONLY late SDK failure'));await attempt
  assert.deepEqual(states,before)
})

test('unconfigured maps emit an explicit state and never load or reset the SDK',async()=>{
  const states:MapStatus[]=[]
  const lifecycle=new MapLoading({configured:false,load:()=>assert.fail('No SDK without configuration'),reset:()=>assert.fail('No reset without configuration'),draw:()=>assert.fail('No drawing without configuration'),destroy:()=>{},status:value=>states.push(value)})
  await lifecycle.start();await lifecycle.retry();lifecycle.redraw();lifecycle.dispose()
  assert.deepEqual(states,['unconfigured'])
})

test('a later props redraw failure cleans residual overlays and requires manual recovery using latest props',async()=>{
  const drawn:number[]=[],states:MapStatus[]=[]
  let day=0,broken=false,loads=0,resets=0,cleanups=0
  const lifecycle=new MapLoading({configured:true,load:async()=>{loads++;return {}},reset:()=>{resets++},
    draw:()=>{if(broken)throw Error('TEST ONLY fitView failed');drawn.push(day)},destroy:()=>{cleanups++},status:value=>states.push(value)})
  await lifecycle.start();broken=true;day=1;lifecycle.redraw()
  assert.equal(lifecycle.state,'error');assert.equal(states.at(-1),'error');assert.ok(cleanups>=2)
  broken=false;day=2;lifecycle.redraw();assert.deepEqual(drawn,[0])
  await lifecycle.retry();assert.deepEqual(drawn,[0,2]);assert.equal(lifecycle.state,'ready');assert.equal(loads,2);assert.equal(resets,0)
})

test('SDK reset failure remains an error and another explicit retry can recover',async()=>{
  let loads=0,resets=0
  const states:MapStatus[]=[]
  const lifecycle=new MapLoading({configured:true,load:async()=>{if(++loads===1)throw Error('TEST ONLY loader failure');return {}},
    reset:()=>{if(++resets===1)throw Error('TEST ONLY reset failure')},draw:()=>{},destroy:()=>{},status:value=>states.push(value)})
  await lifecycle.start();await lifecycle.retry()
  assert.equal(lifecycle.state,'error');assert.equal(loads,1);assert.equal(resets,1)
  await lifecycle.retry()
  assert.equal(lifecycle.state,'ready');assert.equal(loads,2);assert.equal(resets,2)
  assert.ok(states.every(value=>['loading','ready','error'].includes(value)))
})
