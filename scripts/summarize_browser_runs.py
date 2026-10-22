"""Verify a complete immutable 3-browser x 3-suite evidence matrix."""
import argparse
import json
from pathlib import Path
from browser_runs import run_id,verify_report
ROOT=Path(__file__).resolve().parents[1]

def summarize(identifier):
    identifier=run_id(identifier);matrix=[]
    for browser in ['chromium','firefox','webkit']:
        for suite in ['local','auth','resilience']:
            path=ROOT/'artifacts/browser-runs'/identifier/browser/suite
            meta=json.loads((path/'run.json').read_text(encoding='utf-8'))
            if meta.get('run_id')!=identifier or meta.get('browser')!=browser or meta.get('suite')!=suite or not meta.get('complete_suite') or not meta.get('passed') or not meta.get('services_stopped_gracefully'):
                raise ValueError('Incomplete or mismatched run metadata')
            count=verify_report(json.loads((path/'report.json').read_text(encoding='utf-8')),meta['planned_cases'])
            if count!=meta['passed_count']:raise ValueError('Count differs from verified metadata')
            matrix.append({'browser':browser,'suite':suite,'passed':count})
    return {'run_id':identifier,'all_passed':True,'matrix':matrix,'executions':sum(x['passed'] for x in matrix),'retries':0,'skipped':0}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True);args=parser.parse_args()
    try:
        result=summarize(args.run_id)
        path=ROOT/'artifacts/browser-runs'/args.run_id/'summary.json'
        path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
    except (OSError,ValueError,KeyError,TypeError):parser.exit(1,'Browser evidence is missing, incomplete or inconsistent.\n')
if __name__=='__main__':main()
