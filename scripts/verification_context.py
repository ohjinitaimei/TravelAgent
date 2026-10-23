"""Bind verification evidence to normalized source; never read ignored credentials."""
import hashlib
import json
from pathlib import Path
import subprocess

PREFIXES=('backend/','apps/web/','packages/api-schema/','deploy/','scripts/','tests/')
FILES={'package.json','package-lock.json','playwright.config.ts'}


def selected(name):
    return name.startswith(PREFIXES) or name in FILES


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalized(data):
    if b'\0' not in data[:8000]:
        try:return data.decode('utf-8').replace('\r\n','\n').encode('utf-8')
        except UnicodeError:pass
    return data


def fingerprint(files):
    return digest(json.dumps(sorted(files,key=lambda item:item['path']),sort_keys=True,separators=(',',':')).encode())


def capture(root):
    root=Path(root).resolve()
    def git(*args):
        return subprocess.check_output(['git','-c','safe.directory='+root.as_posix(),*args],cwd=root).decode('utf-8').strip()
    candidates=git('ls-files','-z','--cached','--others','--exclude-standard').split('\0')
    files=[]
    for name in sorted(set(candidates)):
        if not selected(name):continue
        path=root/name
        if path.is_symlink():raise ValueError('Verification source cannot be a symlink')
        if not path.is_file():continue
        data=normalized(path.read_bytes())
        files.append({'path':name,'bytes':len(data),'sha256':digest(data)})
    if not files:raise ValueError('Verification source is empty')
    return {'base_commit':git('rev-parse','HEAD'),'fingerprint':fingerprint(files),'files':files}


def assert_context(context,current):
    if not isinstance(context,dict) or context.get('files')!=current['files'] or context.get('fingerprint')!=current['fingerprint']:
        raise ValueError('Verification evidence belongs to different source')


def tree_digest(folder):
    folder=Path(folder)
    if folder.is_symlink():raise ValueError('Build root cannot be a symlink')
    folder=folder.resolve();files=[]
    for path in sorted(folder.rglob('*'),key=lambda path:path.relative_to(folder).as_posix()):
        if path.is_symlink():raise ValueError('Build cannot contain symlinks')
        if not path.is_file():continue
        data=path.read_bytes()
        files.append({'path':path.relative_to(folder).as_posix(),'bytes':len(data),'sha256':digest(data)})
    if not any(item['path']=='index.html' for item in files):raise ValueError('Web build is missing')
    return {'fingerprint':fingerprint(files),'files':files}
