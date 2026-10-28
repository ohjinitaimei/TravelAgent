"""Opt-in fixed three-scenario intake acceptance; isolated DB, no travel queries.

Uses the configured model once per scenario, with no automatic retry. Reports
contain fixed acceptance inputs, not personal records, and are not publishable.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verification_context import assert_context, capture
from browser_runs import run_id
from live_requirements_cases import REVIEW_SCENARIOS
import httpx


def now():
    return datetime.now(timezone.utc).isoformat()


def env_files():
    folders = (ROOT, ROOT / 'backend', ROOT / 'apps/web', ROOT / 'deploy')
    paths = {folder / name for folder in folders for name in ('.env', '.env.local', '.env.production', '.env.production.local')}
    paths.update((ROOT / 'deploy/backend.env', ROOT / 'deploy/gateway.env'))
    return sorted(path for path in paths if path.is_file())


def env_snapshot():
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in env_files()}


def scrub_travel_credentials(env):
    names = set(env)
    for path in env_files():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            names.add(line.split('=', 1)[0].strip().removeprefix('export '))
    names.update(('AMAP_KEY', 'AMAP_WEB_KEY', 'AMAP_API_KEY', 'AMAP_JS_KEY', 'AMAP_JS_SECURITY_CODE',
                  'VITE_AMAP_JS_KEY', 'VITE_AMAP_SECURITY_CODE'))
    for name in names:
        if is_travel_credential(name):
            env[name] = ''


def is_travel_credential(name):
    return name.startswith('VITE_') or (name.startswith('AMAP_') and any(part in name for part in ('KEY', 'SECURITY', 'TOKEN', 'SECRET')))


def audit_db(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        tasks = [json.loads(row[0]) for row in db.execute('SELECT data FROM tasks')]
        events = [json.loads(row[0]) for row in db.execute('SELECT data FROM events')]
        drafts = db.execute('SELECT count(*) FROM drafts').fetchone()[0]
        trips = db.execute('SELECT count(*) FROM itineraries').fetchone()[0]
    return {'task_count': len(tasks), 'task_kinds': [task.get('kind') for task in tasks],
            'task_statuses': [task.get('status') for task in tasks],
            'all_tasks_are_drafts': all(task.get('kind') == 'draft' for task in tasks),
            'draft_count': drafts, 'itinerary_count': trips,
            'agent_call_events': sum(event.get('stage') == 'agent_call' for event in events)}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-model-call',action='store_true',required=True)
    parser.add_argument('--reference-date',required=True)
    parser.add_argument('--date',required=True)
    parser.add_argument('--run-id')
    args=parser.parse_args(argv)
    try:
        reference=date.fromisoformat(args.reference_date).isoformat()
        departure=date.fromisoformat(args.date).isoformat()
        identifier=run_id(args.run_id)
    except ValueError as error:
        parser.error(str(error))
    output = ROOT / 'artifacts/live-requirements-runs' / identifier
    # Reserve the whole evidence namespace before service startup or paid work.
    output.mkdir(parents=True, exist_ok=False)
    context = capture(ROOT)
    original_env = env_snapshot()
    summary = {'status': 'running', 'started_at': now(), 'context': context,
               'run_id':identifier,'planned_scenarios':list(REVIEW_SCENARIOS),
               'reference_date':reference,'departure_date':departure,
               'model_call_upper_bound': len(REVIEW_SCENARIOS),
               'model_call_evidence': 'persisted adapter events plus fixed one-request/no-retry code boundary; not provider billing',
               'scenarios': [], 'planning_requests': 0, 'personal_database_touched': False,
               'system_trust_modified': False, 'configuration_file_modified': False,
               'api': {'returncode': None, 'forced': False, 'graceful': False}, 'cleanup': False}
    api = None
    temporary = None
    api_log = None
    failed = None
    try:
        (ROOT / '.tmp').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='requirements-live-', dir=ROOT / '.tmp')
        work = Path(temporary.name)
        db_path = work / 'travel.sqlite3'
        rate_path = work / 'amap-rate.sqlite3'
        stop = work / 'stop'
        if db_path.exists() or rate_path.exists():
            raise RuntimeError('temporary_database_not_empty')
        env = os.environ.copy()
        scrub_travel_credentials(env)
        env.update(TRAVEL_AGENT_ENABLED='1', LLM_INTENT_DISABLE_LLM='0', TRAVEL_PRODUCTION='1',
                   TRAVEL_AUTH_MODE='local', TRAVEL_COOKIE_SECURE='0', TRAVEL_TOOL_TRANSPORT='direct',
                   TRAVEL_DB_PATH=str(db_path), TRAVEL_AMAP_RATE_DB_PATH=str(rate_path),
                   PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', GIT_CONFIG_COUNT='1',
                   GIT_CONFIG_KEY_0='safe.directory', GIT_CONFIG_VALUE_0=ROOT.as_posix())
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        env['TRAVEL_CORS_ORIGINS'] = origin
        api_log = (output / 'API.log').open('x', encoding='utf-8')
        api = subprocess.Popen([sys.executable, 'scripts/verification_server.py', '--port', str(port),
                                '--stop-file', str(stop)], cwd=ROOT, env=env,
                               stdout=api_log, stderr=subprocess.STDOUT)
        with httpx.Client(base_url=origin, timeout=3, trust_env=False) as client:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if api.poll() is not None:
                    raise RuntimeError('api_startup_failed')
                try:
                    if client.get('/health/ready').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError('api_readiness_deadline')
            capability = client.get('/api/v1/travel/capabilities').raise_for_status().json()
            summary['configuration'] = {name: bool(capability.get(name)) for name in
                ('draft_enabled', 'llm_configured', 'helloagents_available', 'configured', 'map_proxy_configured')}
            summary['configuration']['tool_transport_direct'] = capability.get('tool_transport') == 'direct'
            summary['configuration']['travel_credentials_blank'] = all(not value for key, value in env.items()
                                                                      if is_travel_credential(key))
            summary['configuration']['temporary_database_paths'] = db_path.parent == work and rate_path.parent == work
            if not all(summary['configuration'][name] for name in
                       ('draft_enabled', 'llm_configured', 'helloagents_available', 'tool_transport_direct',
                        'travel_credentials_blank', 'temporary_database_paths')):
                raise RuntimeError('intake_preflight_failed')
            if capability.get('configured') or capability.get('map_proxy_configured'):
                raise RuntimeError('travel_service_must_be_unconfigured')
        print(json.dumps({'preflight': 'passed', 'configuration': summary['configuration']}), flush=True)
        for name in REVIEW_SCENARIOS:
            report_path = output / (name + '.json')
            entry = {'scenario': name, 'started_at': now(), 'report': report_path.relative_to(ROOT).as_posix()}
            summary['scenarios'].append(entry)
            with (output / (name + '.log')).open('x', encoding='utf-8') as log:
                try:
                    result = subprocess.run([sys.executable, 'scripts/verify_live_clarification.py',
                        '--allow-model-call', '--scenario', name, '--base', origin + '/api/v1/travel',
                        '--reference-date', reference, '--date', departure,
                        '--output', str(report_path)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                        timeout=100, check=False)
                    entry['returncode'] = result.returncode
                except subprocess.TimeoutExpired:
                    entry.update(returncode=None, harness_timeout=True)
            entry['completed_at'] = now()
            if report_path.is_file():
                report = json.loads(report_path.read_text(encoding='utf-8'))
                entry.update({key: report.get(key) for key in ('status', 'failed_check', 'error_type',
                    'draft_submission_attempts', 'agent_call_events', 'model_call_upper_bound','extraction_mismatches')})
                if entry.get('status') == 'running':
                    entry['status'] = 'failed'
                    entry['failed_check'] = 'scenario_did_not_finish'
            else:
                entry.update(status='failed', failed_check='scenario_report_missing')
            print(json.dumps({key: entry.get(key) for key in ('scenario', 'status', 'failed_check',
                'draft_submission_attempts', 'agent_call_events', 'model_call_upper_bound')}), flush=True)
    except BaseException as error:
        # Controlled identifiers only; raw errors may contain private network data.
        failed = str(error) if isinstance(error, RuntimeError) and str(error) in {
            'temporary_database_not_empty', 'api_startup_failed', 'api_readiness_deadline',
            'intake_preflight_failed', 'travel_service_must_be_unconfigured'} else type(error).__name__
        summary['failed_check'] = failed
    finally:
        if api is not None:
            if api.poll() is None:
                stop.touch()
                try:
                    api.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    summary['api']['forced'] = True
                    api.terminate()
                    try:
                        api.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        api.kill()
                        api.wait(timeout=5)
            summary['api']['returncode'] = api.returncode
            summary['api']['graceful'] = api.returncode == 0 and not summary['api']['forced']
        if api_log is not None:
            api_log.close()
        if temporary is not None:
            try:
                if db_path.is_file():
                    summary['database'] = audit_db(db_path)
            except BaseException as error:
                summary['database_audit_error'] = type(error).__name__
            try:
                temporary.cleanup()
                summary['cleanup'] = not work.exists()
            except BaseException as error:
                summary['cleanup_error'] = type(error).__name__
        summary['env_files_unchanged'] = original_env == env_snapshot()
        try:
            assert_context(context, capture(ROOT))
            summary['source_unchanged'] = True
        except BaseException:
            summary['source_unchanged'] = False
        db = summary.get('database', {})
        cases = summary['scenarios']
        summary['agent_call_events'] = db.get('agent_call_events')
        summary['external_travel_calls'] = 0 if summary.get('configuration', {}).get('travel_credentials_blank') else None
        summary['travel_call_evidence'] = 'Amap/JS/VITE credentials blank; capability disabled; only draft, clarification and read requests issued'
        summary['status'] = 'passed' if all((failed is None, len(cases) == len(REVIEW_SCENARIOS),
            all(item.get('status') == 'passed' and item.get('returncode') == 0 for item in cases),
            sum(item.get('draft_submission_attempts', 0) for item in cases) == len(REVIEW_SCENARIOS),
            db.get('task_count') == len(REVIEW_SCENARIOS), db.get('all_tasks_are_drafts'), db.get('itinerary_count') == 0,
            db.get('draft_count') == len(REVIEW_SCENARIOS),
            db.get('agent_call_events') == len(REVIEW_SCENARIOS), summary['api']['graceful'], summary['cleanup'],
            summary['source_unchanged'], summary['env_files_unchanged'])) else 'failed'
        summary['completed_at'] = now()
        with (output / 'summary.json').open('x', encoding='utf-8') as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2)
        print(json.dumps({key: summary.get(key) for key in ('status', 'failed_check', 'agent_call_events',
            'model_call_upper_bound', 'api', 'cleanup', 'source_unchanged', 'env_files_unchanged')}), flush=True)
    return 0 if summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
