"""Join current-source evidence with one exact clean archive; no network or publishing."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import zipfile
from browser_runs import run_id
from package_release import LIMIT,verify_archive
from summarize_browser_runs import summarize
from verification_context import capture,assert_context,digest,fingerprint,selected

ROOT=Path(__file__).resolve().parents[1]


def verify(identifier,archive,runtime,root=ROOT):
    root=Path(root).resolve();identifier=run_id(identifier);context=capture(root);evidence=[]
    def read(path):
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        evidence.append({'path':path.relative_to(root).as_posix(),'sha256':digest(path.read_bytes())})
        return value
    repository=read(root/'artifacts/repository-runs'/identifier/'report.json')
    assert_context(repository.get('context'),context)
    planned=sorted(p.relative_to(root).as_posix() for p in (root/'tests').glob('test_*.py'))
    suites=repository.get('python_suites',[])
    if (repository.get('run_id')!=identifier or repository.get('status')!='passed' or repository.get('passed') is not True
        or repository.get('schema_consistent') is not True or repository.get('services_stopped_gracefully') is not True
        or sorted(item['path'] for item in suites)!=planned or len(suites)!=len(planned)
        or not suites or any(type(item.get('passed')) is not int or item['passed']<1 for item in suites)
        or repository.get('python')!=sum(item['passed'] for item in suites)
        or type(repository.get('typescript')) is not int or repository['typescript']<1):
        raise ValueError('Repository evidence is incomplete')
    matrix=summarize(identifier,root=root)
    if archive.stat().st_size>LIMIT:raise ValueError('Archive too large')
    metadata=verify_archive(archive);archive_hash=digest(archive.read_bytes())
    if metadata.get('working_tree_dirty') is not False:raise ValueError('Candidate archive must be a clean commit')
    source=[{**entry,'path':entry['path'][7:]} for entry in metadata['files'] if entry['path'].startswith('source/') and selected(entry['path'][7:])]
    assert_context({'files':source,'fingerprint':fingerprint(source)},context)
    web=[{**entry,'path':entry['path'][4:]} for entry in metadata['files'] if entry['path'].startswith('web/')]
    web_build={'files':web,'fingerprint':fingerprint(web)}
    if metadata.get('verification')!={'context_fingerprint':context['fingerprint'],'web_fingerprint':web_build['fingerprint']}:
        raise ValueError('Archive lacks its source/build binding')
    if repository.get('web_build')!=web_build:raise ValueError('Archive Web differs from repository build')
    for browser in ('chromium','firefox','webkit'):
        for suite in ('local','auth','resilience'):
            folder=root/'artifacts/browser-runs'/identifier/browser/suite
            meta=read(folder/'run.json');read(folder/'report.json')
            if suite=='resilience' and meta.get('web_build')!=web_build:raise ValueError('Browser verified different Web bytes')
    runtime=read(Path(runtime).resolve())
    assert_context(runtime.get('context'),context)
    if (runtime.get('passed')!=4 or runtime.get('externalCalls')!=0 or runtime.get('archive_sha256')!=archive_hash
        or runtime.get('git_commit')!=metadata['git_commit'] or runtime.get('working_tree_dirty') is not False):
        raise ValueError('Runtime evidence belongs to another archive')
    drills={}
    for kind in ('deployment','recovery'):
        folder=root/'artifacts/drill-runs'/identifier/kind
        lifecycle=read(folder/'run.json');report=read(folder/'report.json')
        for record in (lifecycle,report):
            assert_context(record.get('context'),context)
            if (record.get('run_id')!=identifier or record.get('status')!='passed'
                or not all(record.get(field) is True for field in ('services_stopped_gracefully','cleanup_completed','context_unchanged'))
                or not record.get('services') or any(service.get('returncode')!=0 or service.get('forced') is not False for service in record['services'])):
                raise ValueError('Drill evidence is incomplete or cleanup failed')
        if (lifecycle.get('kind')!=kind or lifecycle.get('passed') is not True or type(report.get('passed')) is not int
            or report['passed']!=len(report.get('checks',[])) or report['passed']<1
            or report.get('tlsVerification') is not True or report.get('systemTrustModified') is not False or report.get('externalCalls')!=0):
            raise ValueError('Drill checks or TLS scope do not match')
        if kind=='deployment' and report.get('web_build')!=web_build:raise ValueError('HTTPS verified different Web bytes')
        if kind=='recovery' and (report.get('archive_sha256')!=archive_hash or report.get('release_commit')!=metadata['git_commit']
                               or report.get('archive_source_fingerprint')!=context['fingerprint']):
            raise ValueError('Recovery verified another archive')
        drills[kind]=report['passed']
    return {'status':'passed','run_id':identifier,'timestamp':datetime.now(timezone.utc).isoformat(),'context':context,
        'release_commit':metadata['git_commit'],'archive_sha256':archive_hash,'web_build':web_build,'evidence':evidence,
        'python':repository['python'],'typescript':repository['typescript'],'browser_executions':matrix['executions'],
        'repository_browser_executions':repository['python']+repository['typescript']+matrix['executions'],
        'runtime_checks':4,'drill_checks':drills,'scope':'Local TEST ONLY; no real model/provider/SDK/public server acceptance; hashes are not signatures'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True)
    parser.add_argument('--archive',type=Path,required=True);parser.add_argument('--runtime',type=Path,required=True)
    args=parser.parse_args();identifier=run_id(args.run_id)
    destination=ROOT/'artifacts/candidate-runs'/identifier;destination.mkdir(parents=True,exist_ok=False)
    try:result=verify(identifier,args.archive,args.runtime)
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as error:
        (destination/'report.json').write_text(json.dumps({'status':'failed','run_id':identifier,'error_type':type(error).__name__})+'\n',encoding='utf-8')
        parser.exit(1,'Candidate evidence is missing, stale, mismatched or failed; no files were published.\n')
    (destination/'report.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('status','run_id','release_commit','archive_sha256','repository_browser_executions','runtime_checks','drill_checks')}))


if __name__=='__main__':main()
