"""Build Web and record immutable source/build binding, excluding all credentials."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from browser_runs import run_id
from verification_context import capture,assert_context,tree_digest

ROOT=Path(__file__).resolve().parents[1]


def build(root=ROOT):
    root=Path(root).resolve();context=capture(root)
    destination=root/'artifacts/web-builds'/run_id()
    destination.mkdir(parents=True,exist_ok=False)
    record={'status':'running','context':context,'started_at':datetime.now(timezone.utc).isoformat()}
    path=destination/'build.json'
    def save():path.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
        if not npm:raise ValueError('Node/npm is required')
        subprocess.run([npm,'run','build','--workspace','apps/web'],cwd=root,check=True)
        assert_context(context,capture(root))
        record.update(status='passed',web_build=tree_digest(root/'apps/web/dist'))
    except Exception as error:
        record.update(status='failed',error_type=type(error).__name__)
        raise
    finally:
        record['completed_at']=datetime.now(timezone.utc).isoformat();save()
    # Latest pointer only; each run record is retained independently.
    (root/'artifacts/web-build.json').write_text(json.dumps({'record':path.relative_to(root).as_posix()},indent=2)+'\n',encoding='utf-8')
    return record


def validate(root=ROOT):
    root=Path(root).resolve()
    pointer=json.loads((root/'artifacts/web-build.json').read_text(encoding='utf-8'))
    path=(root/pointer['record']).resolve()
    if not path.is_relative_to(root/'artifacts/web-builds'):raise ValueError('Invalid Web build record')
    record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('status')!='passed':raise ValueError('Web build was not verified')
    assert_context(record.get('context'),capture(root))
    if record.get('web_build')!=tree_digest(root/'apps/web/dist'):raise ValueError('Web build changed after verification')
    return record


if __name__=='__main__':build()
