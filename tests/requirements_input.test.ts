/** TEST ONLY user input and isolated browser storage; no model/provider access. */
import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import type { Draft } from '../apps/web/src/api'
import { clarificationRequest } from '../apps/web/src/draft'
import { ackRequirementsReview, ackRequirementsText, clearRequirementsReview, cloneRequirementsInput, emptyRequirementsInput,
  parseRequirementsInput, requirementsHasChanges, requirementsInputKey, requirementsReview, requirementsSourceMatches,
  requirementsText, RequirementsInputConflict, RequirementsInputStore, selectRequirementsFilled, setRequirementsAnswer,
  setRequirementsSchedules, setRequirementsSelected, setRequirementsText, type RequirementsInput, type StoredRequirementsInput } from '../apps/web/src/requirementsInput'

function draft():Draft {
  return {id:'TEST-ONLY-source',revision:3,input:{text:'TEST ONLY original text',reference_date:'2026-10-24'},
    proposal:{values:{city:'TEST ONLY source city',days:2,budget:null,day_schedules:[
      {day_start:'09:15',day_end:'17:45',stay_minutes:50},{day_start:'10:15',day_end:null,stay_minutes:60}]},
      evidence:{city:'TEST ONLY original evidence'}},confirmed_fields:[],field_sources:{city:'model_extracted'}} as Draft
}
const saved=(input:RequirementsInput):StoredRequirementsInput=>({version:1,input,updatedAt:Date.now()})
function storage(run:(entries:Map<string,string>)=>void){
  const previous=Object.getOwnPropertyDescriptor(globalThis,'localStorage'),entries=new Map<string,string>()
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:(key:string)=>entries.get(key)??null,
    setItem:(key:string,value:string)=>{entries.set(key,value)},removeItem:(key:string)=>{entries.delete(key)}}})
  try{run(entries)}finally{if(previous)Object.defineProperty(globalThis,'localStorage',previous);else Reflect.deleteProperty(globalThis,'localStorage')}
}

test('raw text is owned by the input and survives reconstruction while the original draft remains separate',()=>{
  const source=draft(),before=structuredClone(source),empty=emptyRequirementsInput()
  assert.equal(requirementsText(empty,source),source.input.text);assert.equal(requirementsHasChanges(empty),false)
  const input=setRequirementsText(empty,'TEST ONLY not yet submitted')
  assert.equal(requirementsText(input,source),'TEST ONLY not yet submitted')
  assert.equal(requirementsText(parseRequirementsInput(JSON.stringify(saved(input))).input,source),input.text)
  assert.equal(requirementsText(setRequirementsText(input,''),source),'')
  assert.equal(requirementsText(input,{...source,id:'TEST-ONLY-new'}),input.text)
  assert.deepEqual(source,before);assert.equal(empty.text,null)
})

test('scalar edits retain zero and incomplete raw values without copying model answers or evidence',()=>{
  const source=draft()
  let input=setRequirementsAnswer(emptyRequirementsInput(),source,'budget','0')
  input=setRequirementsAnswer(input,source,'days','1.5')
  input=setRequirementsSelected(input,source,'city',true)
  const raw=JSON.stringify(saved(input)),restored=parseRequirementsInput(raw).input
  assert.deepEqual(restored.clarification?.answers,{budget:'0',days:'1.5'})
  assert.equal(raw.includes('TEST ONLY source city'),false);assert.equal(raw.includes('original evidence'),false)
  const view=requirementsReview(restored,source)!
  assert.equal(view.answers.city,source.proposal.values.city);assert.equal(view.answers.budget,'0');assert.equal(view.selected.city,true)
  assert.throws(()=>clarificationRequest(source,view.answers,view.selected,view.schedules),/范围/)
  input=setRequirementsAnswer(input,source,'days','2')
  const ready=requirementsReview(input,source)!
  assert.equal(clarificationRequest(source,ready.answers,ready.selected,ready.schedules).values.budget,0)
})

test('daily persistence stores only user deltas and reconstructs omitted partial fields from the exact revision',()=>{
  const source=draft(),base=structuredClone(source),view=requirementsReview(emptyRequirementsInput(),source)!
  view.schedules![0].stay_minutes=45;view.schedules![1].day_start=''
  const input=setRequirementsSchedules(emptyRequirementsInput(),source,view.schedules)
  assert.deepEqual(input.clarification?.schedulePatch,{days:{'0':{stay_minutes:45},'1':{day_start:''}}})
  const raw=JSON.stringify(saved(input))
  assert.equal(raw.includes('09:15'),false);assert.equal(raw.includes('17:45'),false)
  const restored=requirementsReview(parseRequirementsInput(raw).input,source)!
  assert.deepEqual(restored.schedules,[{day_start:'09:15',day_end:'17:45',stay_minutes:45},{day_start:'',day_end:'',stay_minutes:60}])
  assert.equal(restored.selected.day_schedules,true);assert.deepEqual(source,base)
  restored.schedules![0].stay_minutes=99
  assert.equal(requirementsReview(input,source)!.schedules![0].stay_minutes,45)
})

test('explicit daily creation removal and clearing preserve count semantics without inherited facts',()=>{
  const source=draft(),view=requirementsReview(emptyRequirementsInput(),source)!
  const less=setRequirementsSchedules(emptyRequirementsInput(),source,[view.schedules![0]])
  assert.equal(less.clarification?.schedulePatch?.count,1)
  assert.equal(requirementsReview(less,source)!.schedules?.length,1)
  const cleared=setRequirementsSchedules(less,source,null)
  assert.deepEqual(cleared.clarification?.schedulePatch,{count:null,days:{}})
  assert.equal(requirementsReview(cleared,source)!.schedules,null)
  const blank={...source,proposal:{...source.proposal,values:{days:2}}}
  const added=setRequirementsSchedules(emptyRequirementsInput(),blank,[{day_start:'',day_end:'',stay_minutes:null},{day_start:'',day_end:'',stay_minutes:null}])
  assert.deepEqual(added.clarification?.schedulePatch,{count:2,days:{}})
  assert.deepEqual(requirementsReview(added,blank)!.schedules,[{day_start:'',day_end:'',stay_minutes:null},{day_start:'',day_end:'',stay_minutes:null}])
})

test('revision and source changes never rebase user edits or confirmations onto new server values',()=>{
  const source=draft(),input=setRequirementsAnswer(emptyRequirementsInput(),source,'city','TEST ONLY unsaved city')
  for(const changed of [null,{...source,id:'TEST-ONLY-other'},{...source,revision:4}]){
    assert.equal(requirementsSourceMatches(input,changed),false)
    if(changed){assert.equal(requirementsReview(input,changed),null);assert.throws(()=>setRequirementsAnswer(input,changed,'budget','0'),/版本不一致/)}
  }
  assert.equal(input.clarification?.answers.city,'TEST ONLY unsaved city')
  const raw=setRequirementsText(input,'TEST ONLY retained text'),cleared=clearRequirementsReview(raw)
  assert.equal(cleared.text,raw.text);assert.equal(cleared.clarification,null);assert.equal(requirementsSourceMatches(cleared,{...source,revision:4}),true)
})

test('receipts acknowledge only the submitted raw text or exact clarification source',()=>{
  const source=draft()
  let input=setRequirementsText(setRequirementsAnswer(emptyRequirementsInput(),source,'budget','0'),'TEST ONLY submitted text')
  assert.equal(ackRequirementsText(input,'TEST ONLY other').text,input.text)
  input=ackRequirementsText(input,'TEST ONLY submitted text')
  assert.equal(input.text,null);assert.equal(input.clarification?.answers.budget,'0')
  const request={expected_revision:3,values:{budget:0},confirm_fields:['budget' as const]}
  const after={...source,revision:4,proposal:{...source.proposal,values:{...source.proposal.values,budget:0}},confirmed_fields:['budget' as const]}
  assert.equal(ackRequirementsReview(input,{...source,revision:2},after,request).clarification,input.clarification)
  assert.equal(ackRequirementsReview(input,source,after,request).clarification,null)
})

test('saving selected budget must retain an edited city that was explicitly left unselected',()=>{
  const source=draft()
  let input=setRequirementsAnswer(emptyRequirementsInput(),source,'city','TEST ONLY unsent city')
  input=setRequirementsSelected(input,source,'city',false)
  input=setRequirementsAnswer(input,source,'budget','0')
  const view=requirementsReview(input,source)!,request=clarificationRequest(source,view.answers,view.selected,view.schedules)
  assert.deepEqual(request.values,{budget:0})
  const after={...source,revision:4,proposal:{...source.proposal,values:{...source.proposal.values,budget:0}},confirmed_fields:['budget' as const]}
  const acknowledged=ackRequirementsReview(input,source,after,request)
  assert.equal(acknowledged.clarification?.answers.city,'TEST ONLY unsent city')
  assert.equal(acknowledged.clarification?.selected.city,false)
  assert.equal(acknowledged.clarification?.answers.budget,undefined)
  assert.equal(acknowledged.clarification?.sourceRevision,4)
  assert.equal(requirementsReview(acknowledged,after)?.answers.city,'TEST ONLY unsent city')
})

test('unselected daily edits survive another selected field and clear only after their own atomic PATCH',()=>{
  const source=draft(),view=requirementsReview(emptyRequirementsInput(),source)!
  view.schedules![0].stay_minutes=45
  let input=setRequirementsSchedules(emptyRequirementsInput(),source,view.schedules)
  input=setRequirementsSelected(input,source,'day_schedules',false)
  input=setRequirementsAnswer(setRequirementsText(input,'TEST ONLY newer text'),source,'budget','0')
  const selected=requirementsReview(input,source)!,request=clarificationRequest(source,selected.answers,selected.selected,selected.schedules)
  assert.deepEqual(request.values,{budget:0})
  const after={...source,revision:4,proposal:{...source.proposal,values:{...source.proposal.values,budget:0}},confirmed_fields:['budget' as const]}
  input=ackRequirementsReview(input,source,after,request)
  assert.equal(input.text,'TEST ONLY newer text')
  assert.equal(input.clarification?.selected.day_schedules,false)
  assert.equal(input.clarification?.schedulePatch?.days['0'].stay_minutes,45)
  assert.equal(requirementsReview(input,after)?.schedules?.[0].stay_minutes,45)
  input=setRequirementsSelected(input,after,'day_schedules',true)
  const daily=requirementsReview(input,after)!,nextRequest=clarificationRequest(after,daily.answers,daily.selected,daily.schedules)
  const next={...after,revision:5,proposal:{...after.proposal,values:{...after.proposal.values,day_schedules:nextRequest.values!.day_schedules}},confirmed_fields:['budget' as const,'day_schedules' as const]}
  input=ackRequirementsReview(input,after,next,nextRequest)
  assert.equal(input.text,'TEST ONLY newer text');assert.equal(input.clarification,null)
})

test('an unsubmitted baseline change retains the old source for explicit conflict review',()=>{
  const source=draft()
  let input=setRequirementsAnswer(emptyRequirementsInput(),source,'city','TEST ONLY unsent')
  input=setRequirementsSelected(input,source,'city',false);input=setRequirementsAnswer(input,source,'budget','0')
  const view=requirementsReview(input,source)!,request=clarificationRequest(source,view.answers,view.selected,view.schedules)
  const unexpected={...source,revision:4,proposal:{...source.proposal,values:{...source.proposal.values,city:'TEST ONLY unexpected server value',budget:0}},confirmed_fields:['budget' as const]}
  const retained=ackRequirementsReview(input,source,unexpected,request)
  assert.equal(retained.clarification?.answers.city,'TEST ONLY unsent');assert.equal(retained.clarification?.answers.budget,undefined)
  assert.equal(retained.clarification?.sourceRevision,3);assert.equal(requirementsSourceMatches(retained,unexpected),false)
})

test('an acknowledgement with the wrong ID, revision, saved value or confirmation never discards input',()=>{
  const source=draft(),input=setRequirementsAnswer(emptyRequirementsInput(),source,'budget','0')
  const request={expected_revision:3,values:{budget:0},confirm_fields:['budget' as const]}
  const after={...source,revision:4,proposal:{...source.proposal,values:{...source.proposal.values,budget:0}},confirmed_fields:['budget' as const]}
  for(const invalid of [{...after,id:'TEST-ONLY-other'},{...after,revision:5},{...after,proposal:source.proposal},{...after,confirmed_fields:[]}]){
    assert.deepEqual(ackRequirementsReview(input,source,invalid,request),input)
  }
  assert.deepEqual(ackRequirementsReview(input,source,after,{...request,expected_revision:2}),input)
})

test('already confirmed unchanged selections can clear without discarding unrelated unselected raw edits',()=>{
  const source={...draft(),confirmed_fields:['city' as const]}
  let input=setRequirementsSelected(emptyRequirementsInput(),source,'city',true)
  input=setRequirementsAnswer(input,source,'query','TEST ONLY held query');input=setRequirementsSelected(input,source,'query',false)
  input=setRequirementsAnswer(input,source,'budget','0')
  const view=requirementsReview(input,source)!,request=clarificationRequest(source,view.answers,view.selected,view.schedules)
  assert.deepEqual(request.confirm_fields,['budget'])
  const after={...source,revision:4,proposal:{...source.proposal,values:{...source.proposal.values,budget:0}},confirmed_fields:['city' as const,'budget' as const]}
  const retained=ackRequirementsReview(input,source,after,request)
  assert.equal(retained.clarification?.selected.city,undefined);assert.equal(retained.clarification?.answers.query,'TEST ONLY held query')
  assert.equal(retained.clarification?.sourceRevision,4)
})

test('selection toggles become clean only when no actual answer or daily edits remain',()=>{
  const source=draft()
  let input=setRequirementsSelected(emptyRequirementsInput(),source,'city',true)
  assert.equal(requirementsHasChanges(input),true)
  input=setRequirementsSelected(input,source,'city',false)
  assert.equal(requirementsHasChanges(input),false);assert.equal(input.clarification,null)
  input=setRequirementsAnswer(input,source,'city','TEST ONLY unselected edit')
  input=setRequirementsSelected(input,source,'city',false)
  assert.equal(requirementsHasChanges(input),true)
  assert.equal(input.clarification?.selected.city,false)
  assert.equal(requirementsReview(input,source)!.answers.city,'TEST ONLY unselected edit')
  input=setRequirementsAnswer(input,source,'city',source.proposal.values.city!)
  input=setRequirementsSelected(input,source,'city',false)
  assert.equal(input.clarification,null)
})

test('selecting all filled values stores confirmations and sparse changes without an answer snapshot',()=>{
  const source=draft(),input=selectRequirementsFilled(emptyRequirementsInput(),source)
  assert.deepEqual(input.clarification?.answers,{})
  assert.equal(input.clarification?.selected.city,true);assert.equal(input.clarification?.selected.day_schedules,true)
  assert.equal(input.clarification?.schedulePatch,null)
  assert.equal(JSON.stringify(input).includes('17:45'),false)
})

test('cloning and edits accept Vue proxies without aliases or structuredClone errors',()=>{
  const source=draft(),input=reactive(setRequirementsAnswer(emptyRequirementsInput(),source,'city','TEST ONLY local'))
  const clone=cloneRequirementsInput(input),changed=setRequirementsAnswer(input,source,'budget',0)
  clone.clarification!.answers.city='TEST ONLY changed clone'
  assert.equal(input.clarification?.answers.city,'TEST ONLY local')
  assert.equal(changed.clarification?.answers.city,'TEST ONLY local');assert.equal(input.clarification?.answers.budget,undefined)
})

test('strict storage validation rejects extra data, source corruption, invalid bounds, expired and future inputs',()=>{
  const input=setRequirementsAnswer(emptyRequirementsInput(),draft(),'city','TEST ONLY local'),value=saved(input),now=Date.now()
  for(const bad of [{...value,provider:{rating:5}},{...value,input:{...input,token:'TEST ONLY forbidden'}},
    {...value,input:{...input,clarification:{...input.clarification,evidence:{city:'not user input'}}}},
    {...value,input:{...input,clarification:{...input.clarification,answers:{poi:{latitude:0}}}}},
    {...value,input:{...input,clarification:{...input.clarification,sourceRevision:0}}},
    {...value,input:{...input,clarification:{...input.clarification,selected:{city:'true'}}}},
    {...value,input:{...input,clarification:{...input.clarification,schedulePatch:{count:1,days:{'2':{day_start:'09:00'}}}}}},
    {...value,input:{...input,text:'x'.repeat(2001)}},
    {...value,version:2},{...value,updatedAt:now-8*86400000},{...value,updatedAt:now+120000}])assert.throws(()=>parseRequirementsInput(JSON.stringify(bad),now))
  assert.throws(()=>parseRequirementsInput('{bad'))
  assert.throws(()=>parseRequirementsInput(JSON.stringify({...value,input:{...input,text:'汉'.repeat(12000)}})),/32 KiB/)
})

test('store reads are passive and owner isolated, while stale tabs cannot overwrite or delete',()=>storage(entries=>{
  const first=new RequirementsInputStore('alpha'),stale=new RequirementsInputStore('alpha'),beta=new RequirementsInputStore('beta')
  first.write(saved(setRequirementsText(emptyRequirementsInput(),'TEST ONLY alpha')))
  beta.write(saved(setRequirementsText(emptyRequirementsInput(),'TEST ONLY beta')))
  const raw=entries.get(requirementsInputKey('alpha'))
  const reopened=new RequirementsInputStore('alpha')
  assert.equal(reopened.draft?.input.text,'TEST ONLY alpha');assert.equal(entries.get(requirementsInputKey('alpha')),raw)
  assert.throws(()=>stale.write(saved(emptyRequirementsInput())),RequirementsInputConflict)
  assert.throws(()=>stale.clear(),RequirementsInputConflict)
  reopened.clear();assert.equal(entries.has(requirementsInputKey('alpha')),false);assert.ok(entries.has(requirementsInputKey('beta')))
}) )

test('quota failures retain the durable copy and current in-memory inputs for later retry',()=>storage(entries=>{
  const source=draft(),store=new RequirementsInputStore('alpha')
  let input=setRequirementsText(emptyRequirementsInput(),'TEST ONLY durable')
  store.write(saved(input));const before=entries.get(requirementsInputKey('alpha')),set=localStorage.setItem
  input=setRequirementsAnswer(setRequirementsText(input,'TEST ONLY newer raw'),source,'budget','0')
  localStorage.setItem=()=>{throw Error('TEST ONLY storage quota')}
  assert.throws(()=>store.write(saved(input)))
  assert.equal(entries.get(requirementsInputKey('alpha')),before)
  assert.equal(store.draft?.input.text,'TEST ONLY durable')
  assert.equal(requirementsReview(input,source)!.answers.budget,'0');assert.equal(requirementsText(input,source),'TEST ONLY newer raw')
  localStorage.setItem=set;store.write(saved(input))
  assert.equal(new RequirementsInputStore('alpha').draft?.input.text,'TEST ONLY newer raw')
}))

test('invalid copies remain for explicit discard and unavailable storage does not throw during construction',()=>storage(entries=>{
  entries.set(requirementsInputKey('alpha'),'{bad')
  const store=new RequirementsInputStore('alpha')
  assert.equal(store.draft,null);assert.match(store.issue,/格式无效/);assert.equal(entries.get(requirementsInputKey('alpha')),'{bad')
  store.clear();assert.equal(entries.size,0)
  const get=localStorage.getItem
  localStorage.getItem=()=>{throw Error('TEST ONLY denied storage')}
  const unavailable=new RequirementsInputStore('beta')
  assert.equal(unavailable.unavailable,true);assert.match(unavailable.issue,/无法读取/)
  localStorage.getItem=get
  unavailable.write(saved(setRequirementsText(emptyRequirementsInput(),'TEST ONLY text')))
  assert.equal(unavailable.unavailable,false)
}))
