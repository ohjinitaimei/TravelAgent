"""Explicit TEST ONLY history records. Never imported by the production server."""
from datetime import date, timedelta
from travel.schemas import Task


def seed_history(store, template, owner='local', count=65):
    result=[]
    for index in range(count):
        trip=template.model_copy(deep=True)
        trip.id=f'test-only-{owner}-history-{index:03d}'
        trip.title=f'TEST ONLY 历史分页 {index:03d}'
        trip.request.city='TEST ONLY 分页城市'
        trip.request.start_date=date(2026,1,1)+timedelta(days=index%10)
        trip.created_at=f'2026-01-{index%28+1:02d}T00:00:00+00:00'
        for day_index,day in enumerate(trip.days):day.date=trip.request.start_date+timedelta(days=day_index)
        trip.parent_id=None
        if index==60:trip.parent_id=f'test-only-{owner}-history-000'
        if index==61:trip.parent_id=f'test-only-{owner}-history-060'
        task=Task(id='test-only-task-'+trip.id,status='running')
        store.register_task(task,{'request':trip.request.model_dump(mode='json')},None,'test-only',owner_id=owner)
        store.succeed(task,trip)
        result.append(trip)
    return result
