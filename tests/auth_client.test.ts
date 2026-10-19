import test from 'node:test'
import assert from 'node:assert/strict'
import { TravelClient, TravelApiError } from '../packages/api-schema/client'
import { workspaceTransport } from '../apps/web/src/workspaceTransport'
import { clearSession, readSession, writeSession } from '../apps/web/src/session'

test('workspace requests bind immutable identity, CSRF and abort to one account',async()=>{
  const calls:{path:string;headers?:Record<string,string>}[]=[]
  let expired=0
  const controller=new AbortController()
  const transport=workspaceTransport(async(path,init)=>{
    calls.push({path,headers:init?.headers})
    if(path==='/itineraries') throw new TravelApiError('workspace_identity_changed','TEST ONLY')
    return {mode:'session',authenticated:false,setup_required:false}
  },'test-alpha','test-only-csrf',controller.signal,()=>{expired++;controller.abort()})
  const api=new TravelClient(transport)
  await api.logout()
  assert.equal(calls[0].headers?.['X-Workspace-User'],'test-alpha')
  assert.equal(calls[0].headers?.['X-CSRF-Token'],'test-only-csrf')
  await assert.rejects(()=>api.itineraries(),error=>error instanceof TravelApiError&&error.code==='workspace_identity_changed')
  assert.equal(expired,1)
  await assert.rejects(()=>api.create({city:'TEST ONLY',query:'TEST ONLY',start_date:'2026-10-20'}))
  assert.equal(calls.length,2)
})

test('workspace restoration uses separate account keys and logout clears only its owner',()=>{
  const entries=new Map<string,string>()
  const previous=Object.getOwnPropertyDescriptor(globalThis,'localStorage')
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:(key:string)=>entries.get(key)??null,setItem:(key:string,value:string)=>entries.set(key,value),removeItem:(key:string)=>entries.delete(key)}})
  try {
    writeSession({taskId:'local-task'})
    writeSession({taskId:'alpha-task'},'test-alpha')
    writeSession({taskId:'beta-task'},'test-beta')
    assert.equal(readSession('test-alpha').taskId,'alpha-task')
    assert.equal(readSession('test-beta').taskId,'beta-task')
    clearSession('test-alpha')
    assert.deepEqual(readSession('test-alpha'),{})
    assert.equal(readSession('test-beta').taskId,'beta-task')
    assert.equal(readSession().taskId,'local-task')
  } finally {
    if(previous) Object.defineProperty(globalThis,'localStorage',previous)
    else Reflect.deleteProperty(globalThis,'localStorage')
  }
})
