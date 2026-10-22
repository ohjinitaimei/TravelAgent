import assert from 'node:assert/strict'
import test from 'node:test'
import type { Draft } from '../apps/web/src/api'
import type { PlanForm } from '../apps/web/src/schedules'
import { handoffAccepted, handoffAnchorsReady, handoffKey } from '../apps/web/src/handoff'
import { restoreForm } from '../apps/web/src/session'

const draft={id:'TEST ONLY',revision:2,proposal:{values:{origin_hint:'TEST ONLY 车站',destination_hint:'TEST ONLY 酒店'}}} as Draft
const form:PlanForm={city:'TEST ONLY',query:'TEST ONLY',start_date:'2026-10-23',days:2,day_origin_poi_id:null,day_destination_poi_id:null}

test('raw endpoint hints never count as selected anchors or confirmation',()=>{
  assert.equal(handoffAnchorsReady(draft,form),false)
  assert.equal(handoffAccepted(draft,form,null),false)
  assert.equal(handoffAccepted(draft,form,{key:handoffKey(draft,form),policy:'selected'}),false)
  assert.equal(handoffAccepted(draft,form,{key:handoffKey(draft,form),policy:'form_only'}),true)
  assert.equal(form.day_origin_poi_id,null)
})

test('all required daily anchors need explicit confirmation for this revision and selection',()=>{
  const value={...form,day_endpoints:[{origin_poi_id:'TEST ONLY home',destination_poi_id:'TEST ONLY return'},{origin_poi_id:'TEST ONLY home2',destination_poi_id:null}]}
  assert.equal(handoffAnchorsReady(draft,value),false)
  value.day_endpoints[1].destination_poi_id='TEST ONLY return2'
  const decision={key:handoffKey(draft,value),policy:'selected' as const}
  assert.equal(handoffAccepted(draft,value,decision),true)
  assert.equal(handoffAccepted({...draft,revision:3},value,decision),false)
  assert.equal(handoffAccepted(draft,{...value,city:'TEST ONLY changed'},decision),false)
  assert.equal(handoffAccepted(draft,{...value,start_date:'2026-10-24'},decision),false)
  value.day_endpoints[0].origin_poi_id='TEST ONLY another'
  assert.equal(handoffAccepted(draft,value,decision),false)
})

test('decision reload retains user inputs only and old drafts need no endpoint acknowledgement',()=>{
  const stored=JSON.parse(JSON.stringify({form,handoffDecision:{key:handoffKey(draft,form),policy:'form_only'}}))
  assert.equal(handoffAccepted(draft,restoreForm(form,stored.form),stored.handoffDecision),true)
  assert.equal(handoffAccepted({proposal:{values:{city:'TEST ONLY'}}} as Draft,form,null),true)
  assert.equal(stored.handoffDecision.key.includes('longitude'),false)
  assert.equal(restoreForm(form,{...form,stay_minutes:null}).stay_minutes,null)
})
