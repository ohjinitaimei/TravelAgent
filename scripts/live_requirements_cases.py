"""User-written requirement scenarios and independent checks, never a parser/provider."""
from copy import deepcopy
from datetime import date as calendar_date, timedelta

FIELDS=('city','query','start_date','days','stops_per_day','day_start','day_end','stay_minutes','mode','budget',
    'day_schedules','max_leg_travel_minutes','max_daily_travel_minutes','origin_hint','destination_hint')
REVIEW_SCENARIOS=('relative-date','ambiguous-constraints','explicit-correction')
SCENARIOS=('legacy','complete15','partial-daily',*REVIEW_SCENARIOS)


class RequirementCheckFailed(AssertionError):
    def __init__(self,check):
        super().__init__(check)
        self.check=check


def require(condition,label):
    if not condition:raise RequirementCheckFailed(label)


def scenario(name,city,date,*,reference=None):
    if name not in SCENARIOS:raise ValueError('Unknown live requirement scenario')
    if name=='legacy':return {'text':'想逛博物馆，需要提前预约。','expected':{'city':None,'query':'博物馆','start_date':None}}
    values=dict.fromkeys(FIELDS)
    if name in REVIEW_SCENARIOS:
        values.update(city=city,query='博物馆',days=2)
        required_unhandled=['需要提前预约']
        if name=='relative-date':
            if reference is None:raise ValueError('Relative date requires an explicit reference date')
            values.update(start_date=(calendar_date.fromisoformat(reference)+timedelta(days=1)).isoformat(),
                day_schedules=[{'day_start':'14:00','day_end':None,'stay_minutes':None},
                    {'day_start':None,'day_end':'16:00','stay_minutes':None}])
            text=f'明天去{city}逛博物馆，玩2天。第1天14:00开始，第2天16:00结束。交通方式、预算和每站停留都还没定，需要提前预约。'
        elif name=='ambiguous-constraints':
            required_unhandled+=['预算600元或800元，还没决定','步行还是驾车还没决定','开始时间09:00或11:00，还没决定']
            text=f'去{city}逛博物馆，玩2天。日期还没定。'+ '；'.join(required_unhandled[1:])+'。需要提前预约。'
        else:
            values.update(start_date=date,stops_per_day=1,mode='walking',budget=600,day_start='10:00',day_end='17:00')
            text=f'{date}去{city}逛博物馆。原先想玩1天、驾车、预算800元，现明确改为玩2天、全程步行、预算600元。每天1站，每天10:00开始、17:00结束。每站停留还没定，需要提前预约。'
        return {'text':text,'expected':values,'required_unhandled':required_unhandled}
    values.update(city=city,query='博物馆',days=2,origin_hint='杭州东站',max_leg_travel_minutes=25)
    if name=='partial-daily':
        values['day_schedules']=[{'day_start':'14:00','day_end':None,'stay_minutes':None},
            {'day_start':None,'day_end':'16:00','stay_minutes':None}]
        text=f'去{city}逛博物馆，玩2天。第1天14:00开始，第2天16:00结束。每段交通最多25分钟，从杭州东站出发。出发日期、交通方式、预算和每站停留都还没定，需要提前预约。'
    else:
        values.update(start_date=date,stops_per_day=1,day_start='09:00',day_end='18:00',stay_minutes=60,
            mode='walking',budget=800,max_leg_travel_minutes=30,max_daily_travel_minutes=90,destination_hint='西湖酒店',
            day_schedules=[{'day_start':'10:00','day_end':'16:00','stay_minutes':45},
                {'day_start':'11:00','day_end':'17:00','stay_minutes':30}])
        text=f'{date}去{city}玩2天，地点关键词是博物馆，每天1站，全程步行，预算800元。共用默认设置为09:00开始、18:00结束、每站停留60分钟；逐日安排不同：第1天10:00开始、16:00结束、默认停留45分钟，第2天11:00开始、17:00结束、默认停留30分钟。每段交通最多30分钟，每天交通最多90分钟，从杭州东站出发，回西湖酒店，需要提前预约。'
    return {'text':text,'expected':values}


def extraction_mismatches(draft,case):
    values=draft.get('proposal',{}).get('values',{})
    return [field for field in FIELDS if field in case['expected'] and values.get(field)!=case['expected'][field]]


def validate_initial(draft,case,name):
    values=draft['proposal']['values'];expected=case['expected']
    require(draft.get('input',{}).get('text')==case['text'],'original_user_text')
    require(draft.get('source')=='helloagents','draft_source')
    require(draft.get('revision')==1,'initial_revision')
    require(draft.get('confirmed_fields')==[],'model_fields_not_confirmed')
    if name!='legacy':require(set(values)==set(FIELDS),'supported_fields')
    for field,value in expected.items():
        require(values.get(field)==value,'extracted_'+field)
        if type(value) is int:require(type(values.get(field)) in (int,float) and not isinstance(values[field],bool),'numeric_'+field)
    nonnull={field for field,value in values.items() if value is not None}
    evidence=draft['proposal']['evidence']
    require(set(evidence)==nonnull,'evidence_fields')
    require(all(isinstance(quote,str) and quote.strip() and quote in case['text'] for quote in evidence.values()),'original_evidence')
    if name!='legacy':
        require(draft.get('field_sources')==dict.fromkeys(nonnull,'model_extracted'),'model_field_sources')
        for field in ('origin_hint','destination_hint'):
            if values[field] is not None:require(values[field] in case['text'],'literal_'+field)
    unhandled=draft['proposal'].get('unhandled_requirements',[])
    require(bool(unhandled) and any('预约' in item for item in unhandled),'unhandled_reservation')
    # Accept a larger continuous quote, but never accept dropping one conflicting clause.
    for index,quote in enumerate(case.get('required_unhandled',[])):
        require(any(quote in item for item in unhandled),'unhandled_clause_'+str(index))
    require(all(isinstance(item,str) and item.strip() and item in case['text'] for item in unhandled),'unhandled_original')
    if values.get('start_date') is None or values.get('day_schedules') is not None or values.get('origin_hint') is not None:
        require(bool(draft.get('questions')),'clarification_questions')


def validate_events(events):
    stages=[item['stage'] for item in events['items']]
    require(stages.count('agent_call')==1,'one_agent_call_event')
    require(stages.count('draft_validated')==1,'one_validated_submission')
    require(stages.count('succeeded')==1,'one_saved_draft')
    require(set(stages)<={'queued','running','agent_call','draft_validated','coordinator','succeeded'},'intake_event_allowlist')


def validate_preserved(before,after):
    require(after['id']==before['id'],'same_draft_id')
    require(after['revision']==before['revision']+1,'next_revision')
    require(after['input']==before['input'],'original_input_preserved')
    require(after['proposal']['unhandled_requirements']==before['proposal']['unhandled_requirements'],'unhandled_preserved')


def validate_confirmation(before,after):
    validate_preserved(before,after)
    require(after['proposal']==before['proposal'],'confirmation_preserves_values_and_evidence')
    expected={key for key,value in before['proposal']['values'].items() if value is not None}
    require(set(after['confirmed_fields'])==expected,'confirmed_expression_fields')
    require(after['field_sources']==before['field_sources'],'confirmation_not_new_user_value')


USER_UPDATE={'max_daily_travel_minutes':75,'budget':0}
CLEAR_FIELDS=('day_schedules','max_leg_travel_minutes','origin_hint','destination_hint')


def validate_user_update(before,after):
    validate_preserved(before,after)
    expected=deepcopy(before['proposal']['values']);expected.update(USER_UPDATE)
    require(after['proposal']['values']==expected,'only_explicit_user_changes')
    for field in USER_UPDATE:
        require(after['field_sources'].get(field)=='user_input','user_field_source_'+field)
        require(field in after['confirmed_fields'],'user_field_confirmed_'+field)
        require(bool(after['proposal']['evidence'].get(field)),'user_evidence_'+field)
    for field in set(expected)-set(USER_UPDATE):
        require(after['proposal']['evidence'].get(field)==before['proposal']['evidence'].get(field),'preserved_evidence_'+field)


def validate_clear(before,after):
    validate_preserved(before,after)
    expected=deepcopy(before['proposal']['values']);expected.update(dict.fromkeys(CLEAR_FIELDS))
    require(after['proposal']['values']==expected,'explicit_clearing_only')
    for field in CLEAR_FIELDS:
        require(field not in after['confirmed_fields'],'cleared_confirmation_'+field)
        require(field not in after['field_sources'],'cleared_source_'+field)
        require(field not in after['proposal']['evidence'],'cleared_evidence_'+field)
    for field in set(expected)-set(CLEAR_FIELDS):
        require(after['proposal']['evidence'].get(field)==before['proposal']['evidence'].get(field),'preserved_evidence_'+field)
