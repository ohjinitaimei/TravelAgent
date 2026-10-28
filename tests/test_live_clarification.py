"""TEST ONLY HTTP/model evidence. No live model, Amap, server or credential is used."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'backend'))
from agent.travel_intake import finish_draft
from travel.drafts import clarify
from travel.provider import TravelFailure
from travel.schemas import DraftRequest,DraftSubmission,DraftClarificationRequest
from live_requirements_cases import SCENARIOS,scenario,extraction_mismatches,validate_initial,validate_events,RequirementCheckFailed
import verify_live_clarification as live

REFERENCE='2026-10-24';DEPARTURE='2026-10-25'


def fixture(name):
    case=scenario(name,'杭州',DEPARTURE,reference=REFERENCE)
    values=case['expected']
    evidence={field:case['text'] for field,value in values.items() if value is not None}
    return case,finish_draft(DraftRequest(text=case['text'],reference_date=REFERENCE),
        DraftSubmission(values=values,evidence=evidence,unhandled_requirements=case.get('required_unhandled',['需要提前预约'])),lambda *_:None)


class FixtureHttp:
    """In-memory TEST ONLY HTTP contract; actual clarification code is reused."""
    def __init__(self,name):
        _,self.draft=fixture(name)
        self.calls=[]
        self.task={'id':'TEST-ONLY-task','kind':'draft','status':'succeeded','draft_id':self.draft.id,'itinerary_id':None}
        self.events={'items':[{'id':index,'stage':stage,'message':'TEST ONLY event'} for index,stage in enumerate(('agent_call','draft_validated','succeeded'),1)]}

    def handle(self,request):
        path=request.url.path.split('/api/v1/travel',1)[-1]
        self.calls.append((request.method,path))
        if path=='/capabilities':return httpx.Response(200,json=dict.fromkeys(('draft_enabled','llm_configured','helloagents_available'),True))
        if path=='/itineraries':return httpx.Response(200,json={'items':[]})
        if path=='/drafts' and request.method=='POST':
            body=json.loads(request.content)
            assert body==self.draft.input.model_dump(mode='json')
            assert request.headers.get('Idempotency-Key')
            return httpx.Response(202,json={**self.task,'status':'queued'})
        if path=='/tasks/TEST-ONLY-task':return httpx.Response(200,json=self.task)
        if path=='/tasks/TEST-ONLY-task/events':return httpx.Response(200,json=self.events)
        if path=='/drafts/'+self.draft.id:
            if request.method=='PATCH':
                try:self.draft=clarify(self.draft,DraftClarificationRequest.model_validate_json(request.content))
                except ValidationError:return httpx.Response(422,json={'error':{'code':'validation_error'}})
                except TravelFailure as error:return httpx.Response(error.status,json={'error':{'code':error.code}})
            return httpx.Response(200,json=self.draft.model_dump(mode='json'))
        raise AssertionError('Unexpected test-owned request: '+request.method+' '+path)

    def client(self):
        return httpx.Client(base_url='https://test.invalid/api/v1/travel',transport=httpx.MockTransport(self.handle))


class LiveClarificationTests(unittest.TestCase):
    def test_report_lists_all_wrong_fields_instead_of_only_the_first_failure(self):
        case,draft=fixture('relative-date');body=draft.model_dump(mode='json')
        body['proposal']['values'].update(start_date=None,day_start='14:00',day_end='16:00',day_schedules=None)
        self.assertEqual(extraction_mismatches(body,case),['start_date','day_start','day_end','day_schedules'])
        body['proposal']['values']['TEST_ONLY_PRIVATE_FIELD']='TEST_ONLY_PRIVATE_VALUE'
        self.assertNotIn('PRIVATE',str(extraction_mismatches(body,case)))

    def test_relative_calendar_boundaries_use_supplied_reference_not_host_or_departure(self):
        for reference,expected in (('2026-12-31','2027-01-01'),('2028-02-28','2028-02-29'),('2028-02-29','2028-03-01')):
            with self.subTest(reference=reference):
                case=scenario('relative-date','杭州','2030-01-01',reference=reference)
                self.assertEqual(case['expected']['start_date'],expected)
                self.assertIsNone(case['expected']['budget'])
        with self.assertRaises(ValueError):scenario('relative-date','杭州',DEPARTURE)

    def test_undecided_values_and_obsolete_corrections_cannot_pass_the_quality_gate(self):
        mutations=(('ambiguous-constraints','budget',600),('ambiguous-constraints','mode','walking'),
            ('ambiguous-constraints','day_start','09:00'),('explicit-correction','days',1),
            ('explicit-correction','mode','driving'),('explicit-correction','budget',800),
            ('relative-date','start_date',REFERENCE))
        for name,field,value in mutations:
            case,draft=fixture(name);body=draft.model_dump(mode='json')
            validate_initial(body,case,name)
            body['proposal']['values'][field]=value
            with self.subTest(name=name,field=field),self.assertRaisesRegex(RequirementCheckFailed,'extracted_'+field):
                validate_initial(body,case,name)

    def test_all_ambiguous_clauses_must_be_preserved_not_only_reservation(self):
        case,draft=fixture('ambiguous-constraints');body=draft.model_dump(mode='json')
        for quote in case['required_unhandled'][1:]:
            broken=deepcopy(body);broken['proposal']['unhandled_requirements'].remove(quote)
            with self.subTest(quote=quote),self.assertRaisesRegex(RequirementCheckFailed,'unhandled_clause_'):
                validate_initial(broken,case,'ambiguous-constraints')

    def test_both_new_cases_require_actual_values_and_preserve_partial_unknowns(self):
        for name in ('complete15','partial-daily'):
            case,draft=fixture(name);body=draft.model_dump(mode='json')
            validate_initial(body,case,name)
            self.assertEqual(len(body['proposal']['values']),15)
            broken=deepcopy(body)
            broken['proposal']['values']['day_schedules'][0]['stay_minutes']=60
            with self.subTest(name=name),self.assertRaisesRegex(RequirementCheckFailed,'extracted_day_schedules'):
                validate_initial(broken,case,name)
        self.assertIsNone(fixture('partial-daily')[1].proposal.values.start_date)

    def test_empty_draft_cannot_be_misreported_as_success(self):
        case,_=fixture('complete15')
        empty=finish_draft(DraftRequest(text=case['text'],reference_date=REFERENCE),DraftSubmission(values={},evidence={}),lambda *_:None)
        with self.assertRaisesRegex(RequirementCheckFailed,'extracted_city'):
            validate_initial(empty.model_dump(mode='json'),case,'complete15')

    def test_original_evidence_sources_and_unhandled_requirements_are_independently_audited(self):
        case,draft=fixture('complete15');body=draft.model_dump(mode='json')
        for kind in ('wrong_evidence','missing_evidence','wrong_source','confirmed','missing_unhandled','invented_field'):
            broken=deepcopy(body)
            if kind=='wrong_evidence':broken['proposal']['evidence']['city']='TEST ONLY unrelated quote'
            if kind=='missing_evidence':broken['proposal']['evidence'].pop('day_schedules')
            if kind=='wrong_source':broken['field_sources']['day_schedules']='user_input'
            if kind=='confirmed':broken['confirmed_fields']=['city']
            if kind=='missing_unhandled':broken['proposal']['unhandled_requirements']=[]
            if kind=='invented_field':broken['proposal']['values']['poi_id']='TEST ONLY invented ID'
            with self.subTest(kind=kind),self.assertRaises(RequirementCheckFailed):validate_initial(broken,case,'complete15')

    def test_http_scenarios_post_one_draft_clear_fields_and_preserve_revision_without_planning(self):
        for name in SCENARIOS:
            fake=FixtureHttp(name);record={'run_id':'TEST-ONLY-'+name}
            with fake.client() as client:live.verify_http(client,record,name=name,city='杭州',departure=DEPARTURE,reference=REFERENCE)
            self.assertEqual(record['draft_submission_attempts'],1)
            self.assertEqual(record['agent_call_events'],1)
            self.assertTrue(record['no_itinerary_created'])
            self.assertEqual([call for call in fake.calls if call==('POST','/drafts')],[('POST','/drafts')])
            self.assertEqual([call for call in fake.calls if call[0]=='POST'],[('POST','/drafts')])
            self.assertEqual(record['task']['itinerary_id'],None)
            if name!='legacy':
                self.assertIsNone(record['cleared']['proposal']['values']['day_schedules'])
                self.assertEqual(record['updated']['field_sources']['budget'],'user_input')
                self.assertEqual(record['confirmed']['field_sources']['query'],'model_extracted')
                self.assertEqual(record['invalid_error']['error']['code'],'invalid_draft_constraints')
                self.assertEqual(record['stale_error']['error']['code'],'draft_revision_conflict')

    def test_duplicate_or_missing_call_events_fail_before_clarifying_without_extra_submission(self):
        for duplicate in (False,True):
            fake=FixtureHttp('complete15')
            if duplicate:fake.events['items'].append({'id':4,'stage':'agent_call'})
            else:fake.events['items']=[]
            record={'run_id':'TEST-ONLY-events'}
            with fake.client() as client,self.assertRaisesRegex(RequirementCheckFailed,'one_agent_call_event'):
                live.verify_http(client,record,name='complete15',city='杭州',departure=DEPARTURE,reference=REFERENCE)
            self.assertEqual(sum(call==('POST','/drafts') for call in fake.calls),1)
            self.assertFalse(any(method=='PATCH' for method,_ in fake.calls))

    def test_only_intake_events_can_support_a_no_planning_claim(self):
        fake=FixtureHttp('complete15')
        fake.events['items'].append({'id':4,'stage':'poi_search','message':'TEST ONLY unexpected business stage'})
        with self.assertRaisesRegex(RequirementCheckFailed,'intake_event_allowlist'):validate_events(fake.events)

    def test_uncertain_submission_is_not_retried_and_keeps_conservative_one_call_bound(self):
        fake=FixtureHttp('complete15');calls=[]
        def respond(request):
            calls.append((request.method,request.url.path))
            if request.method=='POST':raise httpx.ReadTimeout('TEST ONLY response lost',request=request)
            return fake.handle(request)
        record={'run_id':'TEST-ONLY-uncertain'}
        with httpx.Client(base_url='https://test.invalid/api/v1/travel',transport=httpx.MockTransport(respond)) as client,\
            self.assertRaises(httpx.ReadTimeout):
            live.verify_http(client,record,name='complete15',city='杭州',departure=DEPARTURE,reference=REFERENCE)
        self.assertEqual(sum(method=='POST' for method,_ in calls),1)
        self.assertEqual(record['draft_submission_attempts'],1)
        self.assertIsNone(record['agent_call_events'])
        self.assertEqual(record['model_call_upper_bound'],1)

    def test_existing_report_is_never_overwritten_or_followed_by_a_model_request(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            report=Path(folder)/'report.json';report.write_text('TEST ONLY old success',encoding='utf-8')
            with patch.object(live.httpx,'Client',side_effect=AssertionError('No HTTP client may be created')):
                code=live.main(['--allow-model-call','--reference-date',REFERENCE,'--date',DEPARTURE,'--output',str(report)])
            self.assertEqual(code,1)
            self.assertEqual(report.read_text(encoding='utf-8'),'TEST ONLY old success')

    def test_failure_report_has_terminal_status_without_endpoint_or_exception_secrets(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            report=Path(folder)/'report.json'
            def fail(*_args,**_kwargs):raise httpx.ConnectError('TEST ONLY PRIVATE TOKEN at https://private.invalid/secret')
            with patch.object(live.httpx,'Client',side_effect=fail):
                code=live.main(['--allow-model-call','--reference-date',REFERENCE,'--date',DEPARTURE,'--scenario','complete15','--output',str(report)])
            result=json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(code,1)
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['error_type'],'ConnectError')
            self.assertIn('completed_at',result)
            self.assertNotIn('PRIVATE',report.read_text(encoding='utf-8'))
            self.assertNotIn('private.invalid',report.read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
