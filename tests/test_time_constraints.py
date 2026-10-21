"""TEST ONLY factual matrices verify actionable failures without saving fake trips."""
from contextlib import contextmanager
import os
from pathlib import Path
from queue import Queue
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
from test_travel import FixtureProvider, fixture_worker, PAYLOAD
from test_day_grouping import GeographicFixture, REQUEST
from travel.planner import plan
from travel.provider import TravelFailure
from travel.schemas import Error, PlanRequest
from travel.tools import TravelTools
from travel.worker import run


class TimeConstraintTests(unittest.TestCase):
    def failure(self, request, **options):
        with self.assertRaises(TravelFailure) as caught:
            plan(PlanRequest.model_validate(request),lambda *_:None,provider=options.pop('provider',FixtureProvider()),**options)
        self.assertEqual(caught.exception.code,'time_constraint_exceeded')
        self.assertFalse(caught.exception.retryable)
        return caught.exception.time_constraints

    def test_original_matrix_explains_exact_overrun_without_extra_queries(self):
        provider=FixtureProvider()
        with patch.object(provider,'route',wraps=provider.route) as route:
            details=self.failure({**PAYLOAD,'day_end':'10:30'},provider=provider)
        self.assertEqual(route.call_count,2)
        self.assertEqual(details.available_minutes,90)
        self.assertEqual(details.operation,'plan')
        self.assertEqual(details.days[0].model_dump(),{'day_number':1,'stay_minutes':120,'travel_minutes':37,'required_minutes':157,'overrun_minutes':67})

    def test_per_stop_overrides_and_manual_edit_source_are_preserved(self):
        details=self.failure({**PAYLOAD,'day_end':'10:30','stay_minutes_by_poi':{'fixture-a':40,'fixture-b':20}},
            poi_ids_by_day=[['fixture-a','fixture-b']],parent_id='TEST_ONLY_source',optimize_order=False)
        self.assertEqual(details.source_itinerary_id,'TEST_ONLY_source')
        self.assertEqual(details.operation,'adjust')
        self.assertEqual(details.days[0].required_minutes,97)
        self.assertEqual(details.days[0].overrun_minutes,7)

    def test_all_candidates_infeasible_report_original_partition_only(self):
        provider=GeographicFixture()
        details=self.failure({**REQUEST,'day_end':'10:00'},provider=provider)
        self.assertEqual(details.basis,'original_partition')
        self.assertEqual([d.travel_minutes for d in details.days],[100,100])
        self.assertEqual([d.overrun_minutes for d in details.days],[100,100])
        self.assertLessEqual(len(provider.calls),12)

    def test_production_worker_transports_typed_failure_not_a_partial_trip(self):
        @contextmanager
        def tools(*_): yield TravelTools(FixtureProvider())
        output=Queue()
        with patch('travel.tool_runtime.open_tools',tools):
            run({'request':{**PAYLOAD,'day_end':'10:30'}},output)
        items=[]
        while not output.empty():items.append(output.get_nowait())
        self.assertNotIn('result',[item['kind'] for item in items])
        result=Error.model_validate(items[-1]['data'])
        self.assertEqual(result.time_constraints.days[0].overrun_minutes,67)

    def test_legacy_error_without_diagnostics_remains_readable(self):
        error=Error.model_validate({'code':'time_constraint_exceeded','message':'TEST ONLY historical failure','retryable':False})
        self.assertIsNone(error.time_constraints)

    def wait(self,client,identifier):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            task=client.get(f'/api/v1/travel/tasks/{identifier}').json()
            if task['status'] not in {'queued','running'}:return task
            time.sleep(.1)
        self.fail('TEST ONLY task deadline')

    def test_failed_task_persists_diagnostics_but_no_itinerary_or_same_condition_retry(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as directory, patch.dict(os.environ,{'TRAVEL_DB_PATH':str(Path(directory)/'test.sqlite3'),'TRAVEL_AUTH_MODE':'local'}),patch('travel.tasks.run',fixture_worker):
            with TestClient(app) as client:
                task=self.wait(client,client.post('/api/v1/travel/tasks',json={**PAYLOAD,'day_end':'10:30'}).json()['id'])
                self.assertEqual(task['status'],'failed')
                self.assertIsNone(task['itinerary_id'])
                self.assertFalse(task['retry_available'])
                self.assertEqual(task['error']['time_constraints']['days'][0]['overrun_minutes'],67)
                self.assertEqual(client.post(f"/api/v1/travel/tasks/{task['id']}/retry").status_code,409)
                self.assertEqual(client.get('/api/v1/travel/itineraries').json()['items'],[])
                stream=client.get(f"/api/v1/travel/tasks/{task['id']}/events/stream").text
                self.assertIn('time_constraint_exceeded',stream)
            with TestClient(app) as client:
                self.assertEqual(client.get(f"/api/v1/travel/tasks/{task['id']}").json()['error'],task['error'])

    def test_failed_adjustment_keeps_original_then_explicit_new_submission_succeeds(self):
        from main import app
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as directory,patch.dict(os.environ,{'TRAVEL_DB_PATH':str(Path(directory)/'test.sqlite3'),'TRAVEL_AUTH_MODE':'local'}),patch('travel.tasks.run',fixture_worker),TestClient(app) as client:
            source_task=self.wait(client,client.post('/api/v1/travel/tasks',json=PAYLOAD).json()['id'])
            path='/api/v1/travel/itineraries/'+source_task['itinerary_id']
            original=client.get(path).json()
            edit={'poi_ids_by_day':[['fixture-a','fixture-b']],'day_end':'10:30'}
            failed=self.wait(client,client.post(path+'/adjust',json=edit).json()['id'])
            self.assertEqual(failed['status'],'failed')
            self.assertEqual(failed['error']['time_constraints']['source_itinerary_id'],original['id'])
            self.assertEqual(client.get(path).json(),original)
            self.assertEqual(len(client.get('/api/v1/travel/itineraries').json()['items']),1)
            succeeded=self.wait(client,client.post(path+'/adjust',json={**edit,'day_end':'12:00'}).json()['id'])
            self.assertEqual(succeeded['status'],'succeeded')
            self.assertNotEqual(succeeded['id'],failed['id'])
            self.assertEqual(client.get('/api/v1/travel/itineraries/'+succeeded['itinerary_id']).json()['parent_id'],original['id'])
            self.assertEqual(client.get(path).json(),original)


if __name__=='__main__':unittest.main()
