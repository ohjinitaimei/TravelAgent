import test from 'node:test'
import assert from 'node:assert/strict'
import { intakeReferenceDate } from '../apps/web/src/referenceDate'
import { newSubmission,sendSubmission } from '../apps/web/src/submissions'
import { TravelClient } from '../packages/api-schema/client'

test('Shanghai reference date crosses midnight independently of UTC and browser location',()=>{
  assert.equal(intakeReferenceDate(new Date('2026-10-24T15:59:59Z')),'2026-10-24')
  assert.equal(intakeReferenceDate(new Date('2026-10-24T16:00:00Z')),'2026-10-25')
  assert.equal(intakeReferenceDate(new Date('2026-12-31T16:00:00Z')),'2027-01-01')
  assert.equal(intakeReferenceDate(new Date('2028-02-28T16:00:00Z')),'2028-02-29')
})

test('a pending intake submission keeps its frozen reference date across a later resend',async()=>{
  const pending=newSubmission({kind:'draft',request:{text:'TEST ONLY 明天去杭州',reference_date:intakeReferenceDate(new Date('2026-10-24T15:59:59Z'))}})
  const bodies:unknown[]=[]
  const api=new TravelClient(async(_path,init)=>{bodies.push(init?.body);return {id:'TEST ONLY task',status:'queued'}})
  await sendSubmission(api,pending)
  assert.equal(intakeReferenceDate(new Date('2026-10-24T16:01:00Z')),'2026-10-25')
  await sendSubmission(api,pending)
  assert.equal(pending.operation.kind,'draft')
  if(pending.operation.kind!=='draft')throw Error('Unexpected operation')
  assert.deepEqual(bodies,[pending.operation.request,pending.operation.request])
  assert.equal((bodies[1] as {reference_date:string}).reference_date,'2026-10-24')
})
