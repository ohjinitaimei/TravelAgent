"""Immutable per-run browser evidence, shared by runner and report validation."""
from datetime import datetime, timezone
from pathlib import Path
import re
from uuid import uuid4


def run_id(value=None):
    value=value if value is not None else datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',value):
        raise ValueError('Run ID must be 1-64 letters, digits, underscores or hyphens')
    return value


def reserve(root,identifier,browser,suite):
    identifier=run_id(identifier)
    if browser not in {'chromium','firefox','webkit'} or suite not in {'local','auth','resilience'}:raise ValueError('Unknown browser scope')
    destination=(root/'artifacts/browser-runs'/identifier/browser/suite).resolve()
    destination.relative_to(root.resolve())
    destination.mkdir(parents=True,exist_ok=False) # Existing evidence is never cleaned or reused.
    return destination


def case_keys(report):
    def walk(suite):
        for spec in suite.get('specs',[]):
            for test in spec.get('tests',[]):yield spec,test
        for child in suite.get('suites',[]):yield from walk(child)
    items=[(spec,test) for suite in report.get('suites',[]) for spec,test in walk(suite)]
    keys=[spec['id']+':'+test['projectName'] for spec,test in items]
    if not keys or len(keys)!=len(set(keys)):raise ValueError('Empty or duplicate planned cases')
    return keys,items


def verify_report(report,planned):
    keys,items=case_keys(report)
    if set(keys)!=set(planned) or len(keys)!=len(planned):raise ValueError('Executed cases differ from discovery')
    if report.get('errors') or any(report['stats'].get(key,0) for key in ('unexpected','flaky','skipped')):raise ValueError('Report has failures, skips or retries')
    for _,test in items:
        results=test.get('results',[])
        if test.get('status')!='expected' or len(results)!=1 or results[0].get('status')!='passed' or results[0].get('retry',0)!=0:
            raise ValueError('Case did not pass exactly once')
    return len(items)
