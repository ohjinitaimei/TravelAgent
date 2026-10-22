/** TEST ONLY intake values. No model, POI or route provider is called. */
import assert from 'node:assert/strict'
import test from 'node:test'
import type { Draft, Schema } from '../apps/web/src/api'
import { clarificationRequest, displayDraftValue, draftForm, draftScheduleInputs } from '../apps/web/src/draft'

function draft(values:Schema<'DraftValues'>,confirmed_fields:Draft['confirmed_fields']=[]):Draft {
  return {id:'TEST ONLY draft',revision:3,confirmed_fields,proposal:{values,evidence:{}}} as Draft
}

test('partial extracted daily conditions remain blank and applying does not invent endpoint IDs',()=>{
  const value=draft({city:'TEST ONLY',days:2,day_schedules:[{day_start:'10:00'},{day_end:'16:00',stay_minutes:45}],max_leg_travel_minutes:30,max_daily_travel_minutes:90,origin_hint:'TEST ONLY 酒店',destination_hint:'TEST ONLY 车站'})
  const before=structuredClone(value),form=draftForm(value)
  assert.deepEqual(form.day_schedules,[{day_start:'10:00',day_end:'',stay_minutes:null},{day_start:'',day_end:'16:00',stay_minutes:45}])
  assert.equal(form.max_leg_travel_minutes,30);assert.equal(form.max_daily_travel_minutes,90)
  assert.equal(form.day_origin_poi_id,null);assert.equal(form.day_destination_poi_id,null)
  assert.equal('origin_hint' in form,false);assert.equal('destination_hint' in form,false)
  assert.equal(form.compare_poi_alternatives,false)
  assert.deepEqual(value,before)
  form.day_schedules![0].day_start='11:00'
  assert.equal(value.proposal.values.day_schedules![0].day_start,'10:00')
})

test('daily clarification preserves omissions and sends only explicitly selected user values',()=>{
  const value=draft({days:2,query:'TEST ONLY',day_schedules:[{day_start:'10:00'},{day_end:'16:00'}]})
  const daily=draftScheduleInputs(value)!
  daily[0].stay_minutes=45
  const body=clarificationRequest(value,{query:'NOT SELECTED',max_leg_travel_minutes:'40'},{day_schedules:true,max_leg_travel_minutes:true},daily)
  assert.deepEqual(body.values,{max_leg_travel_minutes:40,day_schedules:[{day_start:'10:00',day_end:null,stay_minutes:45},{day_start:null,day_end:'16:00',stay_minutes:null}]})
  assert.deepEqual(body.confirm_fields,['max_leg_travel_minutes','day_schedules'])
  assert.equal(body.expected_revision,3)
  assert.equal(value.proposal.values.day_schedules![0].stay_minutes,undefined)
})

test('clearing and confirmation use the same typed draft contract without resubmitting unchanged fields',()=>{
  const day={day_start:'10:00',day_end:'16:00',stay_minutes:45}
  const value=draft({days:1,day_schedules:[day],origin_hint:'TEST ONLY 酒店'})
  assert.deepEqual(clarificationRequest(value,{}, {day_schedules:true},[{...day}]),{expected_revision:3,values:{},confirm_fields:['day_schedules']})
  assert.deepEqual(clarificationRequest(value,{origin_hint:''},{origin_hint:true,day_schedules:true},null).values,{origin_hint:null,day_schedules:null})
  assert.throws(()=>clarificationRequest(draft({days:1,day_schedules:[day]},['day_schedules']),{},{day_schedules:true},[{...day}]),/请选择/)
  assert.throws(()=>clarificationRequest(value,{}, {day_schedules:true}),/核对/)
})

test('changes never silently truncate daily values when the travel day count conflicts',()=>{
  const value=draft({days:2,day_schedules:[{day_start:'10:00'},{day_end:'16:00'}]})
  const before=structuredClone(value)
  assert.throws(()=>clarificationRequest(value,{days:1},{days:true}),/与天数不一致/)
  assert.throws(()=>clarificationRequest(value,{days:1},{days:true,day_schedules:true},[{day_start:'10:00',day_end:'',stay_minutes:null},{day_start:'',day_end:'16:00',stay_minutes:null}]),/与天数不一致/)
  assert.deepEqual(clarificationRequest(value,{days:1},{days:true,day_schedules:true},null).values,{days:1,day_schedules:null})
  assert.deepEqual(value,before)
})

test('partial schedules are allowed but invalid windows, sizes, stays and transport limits are rejected',()=>{
  const value=draft({})
  const send=(daily:any)=>clarificationRequest(value,{}, {day_schedules:true},daily)
  for(const daily of [[],Array(4).fill({day_start:'',day_end:'',stay_minutes:null}),[{day_start:'18:00',day_end:'09:00',stay_minutes:60}],[{day_start:'25:00',day_end:'',stay_minutes:null}],[{day_start:'',day_end:'',stay_minutes:9}],[{day_start:'',day_end:'',stay_minutes:10.5}]])assert.throws(()=>send(daily))
  assert.deepEqual(send([{day_start:'',day_end:'',stay_minutes:null}]).values.day_schedules,[{day_start:null,day_end:null,stay_minutes:null}])
  for(const limit of ['0','1440','1.5','NaN'])assert.throws(()=>clarificationRequest(value,{max_leg_travel_minutes:limit},{max_leg_travel_minutes:true}),/范围/)
})

test('review text makes daily unknowns explicit and old drafts still reset all prior constraints',()=>{
  assert.equal(displayDraftValue('day_schedules',[{day_start:'10:00',day_end:null,stay_minutes:null}]),'第 1 天 10:00—结束未说明，停留 未说明')
  assert.equal(displayDraftValue('mode','driving'),'驾车')
  const old=draft({query:'TEST ONLY'})
  assert.equal(draftScheduleInputs(old),null)
  const form=draftForm(old)
  assert.equal(form.day_schedules,null);assert.equal(form.day_endpoints,null)
  assert.equal(form.max_leg_travel_minutes,null);assert.equal(form.max_daily_travel_minutes,null)
  assert.equal(form.start_date,'');assert.equal(form.days,2);assert.equal(form.mode,'walking')
  assert.deepEqual(form.stay_minutes_by_poi,{})
})

test('applying daily drafts requires explicit day count and never creates or resizes daily conditions',()=>{
  const unknown=draft({day_schedules:[{day_start:'10:00'}]})
  const before=structuredClone(unknown)
  assert.throws(()=>draftForm(unknown),/先在草案中确认旅行天数/)
  assert.deepEqual(unknown,before)
  const confirmed=draft({days:2,day_schedules:[{day_start:'10:00'},{day_end:'16:00'}]},['days'])
  assert.deepEqual(draftForm(confirmed).day_schedules,[{day_start:'10:00',day_end:'',stay_minutes:null},{day_start:'',day_end:'16:00',stay_minutes:null}])
})

test('hint bounds are validated while untouched hints and unknowns are left to the existing draft',()=>{
  const value=draft({origin_hint:'TEST ONLY 原文线索',destination_hint:null,max_leg_travel_minutes:null})
  const body=clarificationRequest(value,{origin_hint:'UNSELECTED',max_leg_travel_minutes:30},{max_leg_travel_minutes:true})
  assert.deepEqual(body.values,{max_leg_travel_minutes:30})
  assert.equal(value.proposal.values.origin_hint,'TEST ONLY 原文线索')
  assert.equal(value.proposal.values.destination_hint,null)
  assert.throws(()=>clarificationRequest(value,{origin_hint:'x'.repeat(101)},{origin_hint:true}),/长度/)
  assert.deepEqual(clarificationRequest(value,{origin_hint:'x'.repeat(100)},{origin_hint:true}).values,{origin_hint:'x'.repeat(100)})
})
