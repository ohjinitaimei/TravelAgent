"""TEST ONLY maximum-size response; never configurable in the production provider."""
from test_day_grouping import GeographicFixture
from travel.planner import plan
from travel.schemas import PlanRequest, Point


class MaximumFixture(GeographicFixture):
    def __init__(self):
        super().__init__(count=12)
        for poi in self.pois:
            poi.name='TEST ONLY maximum '+poi.id

    def route(self, a, b, mode):
        segment=super().route(a,b,mode)
        segment.polyline=[Point(longitude=a.longitude+(b.longitude-a.longitude)*i/511,
                                latitude=a.latitude+(b.latitude-a.latitude)*i/511) for i in range(512)]
        return segment


def maximum_fixture_worker(payload,output):
    result=plan(PlanRequest.model_validate(payload['request']),
        lambda stage,message:output.put({'kind':'event','stage':stage,'message':message}),
        provider=MaximumFixture(),poi_ids_by_day=payload.get('poi_ids_by_day'),
        optimize_order=payload.get('optimize_order',True),parent_id=payload.get('parent_id'))
    output.put({'kind':'result','data':result.model_dump(mode='json')})
