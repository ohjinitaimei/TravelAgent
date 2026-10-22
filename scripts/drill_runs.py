"""Isolated drill evidence: unique scopes and success only after verified cleanup."""
from datetime import datetime, timezone
import json
from pathlib import Path

from browser_runs import run_id


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def reserve(root,identifier,kind):
    identifier=run_id(identifier)
    if kind not in {'deployment','recovery'}:raise ValueError('Unknown drill scope')
    root=Path(root).resolve()
    destination=(root/'artifacts/drill-runs'/identifier/kind).resolve()
    destination.relative_to(root)
    destination.mkdir(parents=True,exist_ok=False)
    return destination


def save(destination,document,name='report.json'):
    if name not in {'run.json','report.json'}:raise ValueError('Unknown drill evidence file')
    (destination/name).write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def begin(destination,*,source,context,**details):
    if (destination/'run.json').exists():raise FileExistsError('Drill metadata already exists')
    metadata={**details,'run_id':destination.parent.name,'kind':destination.name,'source':source,
        'context':context,'started_at':timestamp(),'status':'running','passed':False}
    save(destination,metadata,'run.json')
    return metadata


def close_service(process,name,timeout=15):
    """Wait after caller requests graceful stop; retain proof if force was needed."""
    result={'name':name,'returncode':None,'forced':False}
    try:
        process.wait(timeout=timeout)
    except Exception as error:
        result.update(forced=True,shutdown_error_type=type(error).__name__)
        try:
            process.terminate();process.wait(timeout=5)
        except Exception:
            try:process.kill();process.wait(timeout=5)
            except Exception as kill_error:result['kill_error_type']=type(kill_error).__name__
    result['returncode']=process.returncode
    return result


def finish(destination,metadata,*,error=None,services,cleanup_completed,context,**details):
    """Do not turn completed assertions into a pass until their services exit cleanly."""
    graceful=bool(services) and all(type(service.get('returncode')) is int and service['returncode']==0
        and service.get('forced') is False and not service.get('shutdown_error_type') for service in services)
    expected=metadata.get('context',{}).get('fingerprint')
    unchanged=bool(expected) and expected==context.get('fingerprint')
    passed=error is None and graceful and cleanup_completed is True and unchanged
    result={**metadata,**details,'services':services,'services_stopped_gracefully':graceful,
        'cleanup_completed':cleanup_completed is True,'context_unchanged':unchanged,
        'status':'passed' if passed else 'failed','passed':passed,'completed_at':timestamp()}
    if error is not None:result['exceptionType']=type(error).__name__
    if not unchanged:result['completed_context']=context
    save(destination,result,'run.json')
    return result
