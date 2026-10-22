"""Verify a complete immutable 3-browser x 3-suite evidence matrix."""
import argparse
import json
from pathlib import Path
from browser_runs import run_id,verify_report
from verification_context import capture,assert_context,digest
ROOT=Path(__file__).resolve().parents[1]

def summarize(identifier,root=None):
    root=ROOT if root is None else Path(root)
    identifier=run_id(identifier);matrix=[];context=capture(root)
    for browser in ['chromium','firefox','webkit']:
        for suite in ['local','auth','resilience']:
            path=root/'artifacts/browser-runs'/identifier/browser/suite
            meta=json.loads((path/'run.json').read_text(encoding='utf-8'))
            if meta.get('run_id')!=identifier or meta.get('browser')!=browser or meta.get('suite')!=suite or not meta.get('complete_suite') or not meta.get('passed') or not meta.get('services_stopped_gracefully'):
                raise ValueError('Incomplete or mismatched run metadata')
            assert_context(meta.get('context'),context)
            if meta.get('report_sha256')!=digest((path/'report.json').read_bytes()):raise ValueError('Browser report changed after verification')
            count=verify_report(json.loads((path/'report.json').read_text(encoding='utf-8')),meta['planned_cases'])
            if count!=meta['passed_count']:raise ValueError('Count differs from verified metadata')
            matrix.append({'browser':browser,'suite':suite,'passed':count})
    return {'run_id':identifier,'all_passed':True,'context':context,'matrix':matrix,'executions':sum(x['passed'] for x in matrix),'retries':0,'skipped':0}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True);args=parser.parse_args()
    try:
        result=summarize(args.run_id)
        path=ROOT/'artifacts/browser-runs'/args.run_id/'summary.json'
        path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
    except (OSError,ValueError,KeyError,TypeError):parser.exit(1,'Browser evidence is missing, incomplete or inconsistent.\n')
if __name__=='__main__':main()
