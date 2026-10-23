"""Opt-in one-model-call requirement/clarification checks over HTTP; no travel queries."""
import argparse
from datetime import date,datetime,timezone
import json
from pathlib import Path
import time
from urllib.parse import quote

import httpx
from browser_runs import run_id
from live_requirements_cases import (SCENARIOS,CLEAR_FIELDS,USER_UPDATE,RequirementCheckFailed,require,
    scenario,validate_initial,validate_events,validate_confirmation,validate_user_update,validate_clear)

ROOT=Path(__file__).resolve().parents[1]


def verify_http(client,record,*,name,city,departure,reference):
    case=scenario(name,city,departure);task=None
    record.update(scenario=name,request={'text':case['text'],'reference_date':reference},expected=case['expected'],
        draft_submission_attempts=0,model_call_upper_bound=1,agent_call_events=None,
        model_call_evidence='persisted adapter event; pinned single-request/no-retry boundary, not provider billing',
        planning_requests=0,travel_provider_called=False,browser_interaction_verified=False,via_http=True)
    try:
        capability=client.get('/capabilities').raise_for_status().json()
        require(all(capability.get(field) for field in ('draft_enabled','llm_configured','helloagents_available')),'intake_configuration')
        before=client.get('/itineraries').raise_for_status().json()
        record['draft_submission_attempts']=1
        # Exactly one draft POST. An uncertain receipt or failure is never replayed.
        task=client.post('/drafts',json=record['request'],headers={'Idempotency-Key':'live-intake-'+record['run_id']}).raise_for_status().json()
        record['task']=task
        require(task.get('kind')=='draft' and task.get('itinerary_id') is None,'draft_task_only')
        task_path='/tasks/'+quote(task['id'],safe='')
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            task=client.get(task_path).raise_for_status().json();record['task']=task
            if task['status'] not in {'queued','running'}:break
            time.sleep(.3)
        else:raise RequirementCheckFailed('task_deadline')
        events=client.get(task_path+'/events').raise_for_status().json()
        record['events']=events
        record['agent_call_events']=sum(item.get('stage')=='agent_call' for item in events.get('items',[]))
        require(task['status']=='succeeded' and task.get('draft_id') and task.get('itinerary_id') is None,'draft_task_succeeded')
        validate_events(events)
        record['live_model']=True
        url='/drafts/'+quote(task['draft_id'],safe='')
        initial=client.get(url).raise_for_status().json();record['initial']=initial
        require(initial.get('id')==task['draft_id'],'task_draft_identity')
        require(initial.get('input',{}).get('reference_date')==reference,'reference_date_preserved')
        validate_initial(initial,case,name)
        if name=='legacy':
            first=client.patch(url,json={'expected_revision':initial['revision'],'values':{'city':city},'confirm_fields':['query']}).raise_for_status().json()
            second=client.patch(url,json={'expected_revision':first['revision'],'values':{'start_date':departure,'budget':0}}).raise_for_status().json()
            record.update(first=first,second=second)
            require(second['id']==initial['id'] and second['revision']==initial['revision']+2,'legacy_revision')
            require(second['proposal']['values']['city']==city and second['proposal']['values']['start_date']==departure,'legacy_user_values')
            require({'city','query','start_date','budget'}<=set(second['confirmed_fields']),'legacy_confirmed_fields')
            require(second['proposal']['values']['budget']==0 and second['questions']==[],'legacy_completed')
            require(second['proposal']['unhandled_requirements']==initial['proposal']['unhandled_requirements'],'legacy_unhandled_preserved')
            previous_revision=first['revision'];final=second
        else:
            nonnull=[field for field,value in initial['proposal']['values'].items() if value is not None]
            confirmed=client.patch(url,json={'expected_revision':initial['revision'],'confirm_fields':nonnull}).raise_for_status().json()
            record['confirmed']=confirmed;validate_confirmation(initial,confirmed)
            updated=client.patch(url,json={'expected_revision':confirmed['revision'],'values':USER_UPDATE}).raise_for_status().json()
            record['updated']=updated;validate_user_update(confirmed,updated)
            final=client.patch(url,json={'expected_revision':updated['revision'],'values':dict.fromkeys(CLEAR_FIELDS)}).raise_for_status().json()
            record['cleared']=final;validate_clear(updated,final)
            invalid=client.patch(url,json={'expected_revision':final['revision'],'values':{'day_schedules':[{}]}})
            require(invalid.status_code==422,'merged_daily_count_rejected')
            record['invalid_error']=invalid.json()
            require(client.get(url).raise_for_status().json()==final,'invalid_merge_preserves_draft')
            previous_revision=updated['revision']
        stale=client.patch(url,json={'expected_revision':previous_revision,'values':{'city':'上海'}})
        require(stale.status_code==409,'stale_revision_rejected')
        require(stale.json()['error']['code']=='draft_revision_conflict','stale_error_code')
        record['stale_error']=stale.json()
        require(client.get(url).raise_for_status().json()==final,'conflict_preserves_draft')
        require(client.get('/itineraries').raise_for_status().json()==before,'no_itinerary_created')
        require(client.get(task_path).raise_for_status().json()==task,'clarification_does_not_change_task')
        after_events=client.get(task_path+'/events').raise_for_status().json()
        require(after_events==events,'clarification_no_additional_model_events')
        record.update(final=final,itinerary_count=len(before['items']),no_itinerary_created=True,
            clarification_model_calls=0,live_model=True)
    except BaseException:
        if task and task.get('status') in {'queued','running'}:
            record['cancellation_requested']=True
            try:client.post('/tasks/'+quote(task['id'],safe='')+'/cancel').raise_for_status()
            except Exception:record['cancellation_confirmed']=False
            else:record['cancellation_confirmed']=True
        raise
    return record


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-model-call',action='store_true',required=True)
    parser.add_argument('--base',default='http://127.0.0.1:5173/api/v1/travel')
    parser.add_argument('--reference-date',required=True)
    parser.add_argument('--date',required=True)
    parser.add_argument('--city',default='杭州')
    parser.add_argument('--scenario',choices=SCENARIOS,default='legacy')
    parser.add_argument('--output',type=Path,help='New report path; existing evidence is never overwritten')
    args=parser.parse_args(argv)
    try:reference=date.fromisoformat(args.reference_date).isoformat();departure=date.fromisoformat(args.date).isoformat()
    except ValueError:parser.error('Use valid ISO dates')
    if not args.city.strip() or len(args.city)>60:parser.error('City must contain 1-60 nonblank characters')
    identifier=run_id()
    output=args.output or ROOT/'artifacts/live-clarification-runs'/identifier/'report.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    record={'run_id':identifier,'status':'running','scenario':args.scenario,'live_model_requested':True,
        'started_at':datetime.now(timezone.utc).isoformat(),'model_call_upper_bound':1,
        'draft_submission_attempts':0,'agent_call_events':None}
    # Reserve before issuing any request, including configuration reads.
    try:
        with output.open('x',encoding='utf-8') as stream:json.dump(record,stream,ensure_ascii=False,indent=2)
    except FileExistsError:
        print('Report already exists; no request was issued.');return 1
    try:
        with httpx.Client(base_url=args.base,timeout=20,trust_env=False) as client:
            verify_http(client,record,name=args.scenario,city=args.city,departure=departure,reference=reference)
        record['status']='passed'
    except BaseException as error:
        record.update(status='failed',error_type=type(error).__name__)
        if isinstance(error,RequirementCheckFailed):record['failed_check']=error.check
    finally:
        record['completed_at']=datetime.now(timezone.utc).isoformat()
        output.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:record.get(key) for key in ('status','scenario','draft_submission_attempts','agent_call_events','model_call_upper_bound','failed_check')},ensure_ascii=False))
    return 0 if record['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
