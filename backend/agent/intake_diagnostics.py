"""Finite diagnostic vocabulary; never serialize validation inputs, messages or context."""
from travel.schemas import DraftValidationDiagnostics, DraftValidationIssue, DraftValues


def diagnostics(errors):
    issues=[]
    for error in errors:
        loc=error.get('loc',())
        path='submission'
        if loc and loc[0] in {'values','evidence','unhandled_requirements'}:
            path=loc[0]
            if path=='values' and len(loc)>1 and loc[1] in DraftValues.model_fields:
                path+='.'+loc[1]
                if loc[1]=='day_schedules' and len(loc)>2 and type(loc[2]) is int and 0<=loc[2]<=2:
                    path+='.'+str(loc[2])
                    if len(loc)>3 and loc[3] in {'day_start','day_end','stay_minutes'}:
                        path+='.'+loc[3]
        kind=error.get('type','')
        reason=('missing' if kind=='missing' else 'unexpected_field' if kind=='extra_forbidden'
                else 'range' if kind in {'greater_than_equal','less_than_equal','too_long','too_short','string_too_short','string_too_long'}
                else 'format' if kind in {'string_pattern_mismatch','date_from_datetime_parsing','date_parsing','literal_error'}
                else 'type' if kind.endswith(('_type','_parsing')) else 'constraint')
        issue=DraftValidationIssue(path=path,reason=reason)
        if issue not in issues:issues.append(issue)
        if len(issues)==8:break
    return DraftValidationDiagnostics(issues=issues or [DraftValidationIssue(path='submission',reason='constraint')])
