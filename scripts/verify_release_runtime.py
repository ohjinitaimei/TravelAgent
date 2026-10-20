"""Start a trusted, verified release in an isolated directory with an empty TEST ONLY DB."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from package_release import LIMIT, ROOT, verify_archive


def verify_runtime(archive):
    if archive.stat().st_size>LIMIT:raise ValueError('发布包超过大小上限')
    data=archive.read_bytes();metadata=verify_archive(io.BytesIO(data))
    (ROOT/'.tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release-runtime-',dir=ROOT/'.tmp') as name:
        folder=Path(name)
        # Entries, sizes, duplicates and symlinks were checked against these exact bytes.
        with zipfile.ZipFile(io.BytesIO(data)) as zipped:zipped.extractall(folder)
        env=dict(os.environ,TRAVEL_DB_PATH=str(folder/'test-only.sqlite3'),TRAVEL_PRODUCTION='1',
            TRAVEL_AUTH_MODE='session',TRAVEL_COOKIE_SECURE='1',TRAVEL_AGENT_ENABLED='0',LLM_INTENT_DISABLE_LLM='1',
            TRAVEL_TOOL_TRANSPORT='direct',TRAVEL_CORS_ORIGINS='https://testserver',
            TRAVEL_SESSION_TTL='28800',TRAVEL_SESSION_IDLE_TTL='1800',PYTHONDONTWRITEBYTECODE='1')
        env.pop('PYTHONPATH',None)
        for key in ['AMAP_KEY','AMAP_WEB_KEY','AMAP_JS_KEY','AMAP_JS_SECURITY_CODE','DASHSCOPE_API_KEY',
                    'OPENAI_API_KEY','TRAVEL_LLM_API_KEY','VITE_AMAP_JS_KEY','VITE_AMAP_SECURITY_CODE']:
            env[key]=''
        code='''
from pathlib import Path
import json, sys
sys.path.insert(0,str(Path('backend').resolve()))
from main import app
assert Path(sys.modules['main'].__file__).resolve().is_relative_to(Path.cwd().resolve())
from fastapi.testclient import TestClient
with TestClient(app) as client:
    assert client.get('/health/live').json()=={'status':'alive'}
    ready=client.get('/health/ready')
    assert ready.status_code==200 and ready.json()=={'status':'ready'}
    assert client.get('/api/v1/travel/itineraries').status_code==401
    status=client.get('/api/v1/travel/auth/status').json()
    assert status['mode']=='session' and not status['authenticated'] and status['setup_required']
print(json.dumps({'passed':4,'source':'verified archive, empty TEST ONLY database','externalCalls':0}))
'''
        child=subprocess.run([sys.executable,'-c',code],cwd=folder/'source',env=env,capture_output=True,text=True,timeout=30)
        if child.returncode:raise ValueError('归档程序启动验证失败')
        result=json.loads(child.stdout.splitlines()[-1])
        result.update(git_commit=metadata['git_commit'],working_tree_dirty=metadata['working_tree_dirty'])
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path)
    args=parser.parse_args()
    try:print(json.dumps(verify_runtime(args.archive),ensure_ascii=False))
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired,zipfile.BadZipFile):
        parser.exit(1,'受信任发布包的隔离启动检查失败；未修改业务库或调用外部数据。\n')


if __name__=='__main__':main()
