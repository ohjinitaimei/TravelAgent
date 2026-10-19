"""User clarification of the same draft. Never invokes a model or provider."""
from pydantic import ValidationError

from agent.travel_intake import finish_draft
from travel.provider import TravelFailure
from travel.schemas import Draft, DraftClarification, DraftClarificationRequest, DraftSubmission, DraftValues, now


def clarify(draft: Draft, request: DraftClarificationRequest) -> Draft:
    if request.expected_revision != draft.revision:
        raise TravelFailure("draft_revision_conflict", "草案已在其他页面更新，请先加载最新版本后核对补充内容", status=409)
    changes = request.values.model_dump(mode="json", exclude_unset=True)
    merged = {**draft.proposal.values.model_dump(mode="json"), **changes}
    try:
        values = DraftValues.model_validate(merged)
    except ValidationError:
        raise TravelFailure("invalid_draft_constraints", "补充后的字段不符合约束，请检查每日时段及允许范围", status=422) from None
    if any(merged[field] is None for field in request.confirm_fields):
        raise TravelFailure("missing_confirmation_value", "不能确认空字段，请先填写具体内容", status=422)
    confirmed = set(draft.confirmed_fields) | set(request.confirm_fields)
    sources = dict(draft.field_sources)
    evidence = dict(draft.proposal.evidence)
    for field, value in changes.items():
        if value is None:
            confirmed.discard(field)
            sources.pop(field, None)
            evidence.pop(field, None)
        else:
            confirmed.add(field)
            sources[field] = "user_input"
            evidence[field] = str(value)
    proposal = DraftSubmission(values=values, evidence=evidence,
                               unhandled_requirements=list(draft.proposal.unhandled_requirements))
    reviewed = finish_draft(draft.input, proposal, lambda *_: None)
    entry = DraftClarification(revision=draft.revision + 1, values=changes,
                               confirmed_fields=sorted(set(request.confirm_fields) | {field for field,value in changes.items() if value is not None}))
    return draft.model_copy(update={"proposal": proposal, "questions": reviewed.questions,
        "warnings": reviewed.warnings, "coordinator_action": reviewed.coordinator_action,
        "revision": entry.revision, "updated_at": now(), "confirmed_fields": sorted(confirmed),
        "field_sources": sources, "clarifications": [*draft.clarifications, entry]})
