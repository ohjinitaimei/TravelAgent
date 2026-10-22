"""Deterministic source + built Web ZIP, with verified inventory and no runtime data."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

from dotenv import dotenv_values
from update_publish_manifest import ROOT, MANIFEST, inventory

BLOCKED={'.git','.tmp','.cache','.venv','__pycache__','node_modules','artifacts','backups','data'}
LIMIT=256*1024*1024


def digest(data):return hashlib.sha256(data).hexdigest()


def safe_path(name):
    parts=PurePosixPath(name).parts
    return (bool(parts) and not name.startswith('/') and '\\' not in name and ':' not in name
            and not any(p in {'.','..'} or p.lower() in BLOCKED for p in parts)
            and str(PurePosixPath(name))==name)


def source_allowed(name):
    if not safe_path(name):return False
    filename=PurePosixPath(name).name.lower()
    if filename.endswith('.env.example'):return True
    return not (filename=='.env' or filename.endswith('.env') or '.env.' in filename
                or filename in {'id_rsa','id_ed25519','id_ecdsa','id_dsa','key.properties'}
                or re.search(r'\.(sqlite3?|db)(?:-(?:wal|shm|journal))?$|\.(pem|key|pfx|p12|p8|ppk|jks|keystore|pyc|log)$',filename)
                or name.startswith('backend/pois') and filename.endswith('.json'))


def normalized(data):
    if b'\0' not in data[:8000]:
        try:return data.decode('utf-8').replace('\r\n','\n').encode('utf-8')
        except UnicodeError:pass
    return data


def verify_archive(archive):
    with zipfile.ZipFile(archive) as zipped:
        infos=zipped.infolist();names=[i.filename for i in infos]
        if (len(infos)>5000 or len({n.casefold() for n in names})!=len(names)
            or sum(i.file_size for i in infos)>LIMIT or any(not safe_path(n) for n in names)):
            raise ValueError('发布包路径、大小或重复条目无效')
        if 'RELEASE.json' not in names or zipped.getinfo('RELEASE.json').file_size>2*1024*1024:
            raise ValueError('发布包清单缺失或过大')
        metadata=json.loads(zipped.read('RELEASE.json'))
        if not isinstance(metadata,dict) or metadata.get('format')!=1 or not isinstance(metadata.get('files'),list):raise ValueError('发布格式无效')
        expected={item['path']:item for item in metadata['files']}
        if len(expected)!=len(metadata['files']) or set(expected)!=(set(names)-{'RELEASE.json'}):
            raise ValueError('发布文件与清单不一致')
        for info in infos:
            if info.file_size>50*1024*1024 or info.flag_bits&1 or stat.S_ISLNK(info.external_attr>>16):
                raise ValueError('不支持的发布条目')
            if info.filename=='RELEASE.json':continue
            name=info.filename
            if not (name.startswith('source/') and source_allowed(name[7:]) or name.startswith('web/') and source_allowed(name[4:])):
                raise ValueError('发布包包含非发布文件')
            content=zipped.read(name);entry=expected[name]
            if len(content)!=entry['bytes'] or digest(content)!=entry['sha256']:raise ValueError('发布文件校验失败')
        source=json.loads(zipped.read('source/PUBLISH_MANIFEST.json'))
        source_files={item['path']:item for item in source['files']}
        if len(source_files)!=len(source['files']) or set(source_files)!={n[7:] for n in names if n.startswith('source/') and n!='source/PUBLISH_MANIFEST.json'}:
            raise ValueError('源码清单与归档不一致')
        for name,item in source_files.items():
            actual=expected['source/'+name]
            if (item['bytes'],item['sha256'])!=(actual['bytes'],actual['sha256']):raise ValueError('源码清单校验失败')
        if not {'web/index.html'}<=set(names) or not any(n.startswith('web/assets/') and n.endswith('.js') for n in names):
            raise ValueError('生产 Web 构建缺失')
        return metadata


def build_release(output,web,credential_env=None,root=ROOT):
    root=root.resolve();output=output.absolute()
    if web.is_symlink():raise ValueError('静态根目录不得为符号链接')
    web=web.resolve()
    if (output.is_symlink() or root.is_relative_to(output.resolve()) or output.resolve().is_relative_to(web)
        or output.resolve().is_relative_to(root) and not any(output.resolve().is_relative_to(root/name) for name in ('artifacts','.tmp'))):
        raise ValueError('输出目录不得覆盖源码、静态目录或使用符号链接')
    manifest=json.loads((root/MANIFEST.name).read_text(encoding='utf-8'))
    binding=None
    if root==ROOT:
        if manifest!=inventory():raise ValueError('源码清单已过期，请先更新并校验')
        from verify_web_build import validate
        binding=validate(root) # Reject stale source/build combinations before creating any archive.
    if not (web/'index.html').is_file() or not (web/'assets').is_dir():raise ValueError('须提供已构建的 Web dist')
    configured=list(os.environ.items())
    if credential_env and credential_env.is_file():configured.extend(dotenv_values(credential_env,interpolate=False).items())
    secrets=[v.encode() for k,v in configured if v and len(v)>=12 and k!='AMAP_JS_KEY'
             and (k.endswith(('API_KEY','SECURITY_CODE','TOKEN','SECRET')) or k in {'AMAP_WEB_KEY','AMAP_KEY'})]
    payload={}
    def add(name,path,normalize=False):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root if name.startswith('source/') else web):
            raise ValueError('发布源文件无效')
        if path.stat().st_size>50*1024*1024:raise ValueError('单文件超出发布上限')
        content=path.read_bytes();content=normalized(content) if normalize else content
        if any(secret in content for secret in secrets):raise ValueError('源码或 Web 构建中发现后端凭证')
        payload[name]=content
    for entry in manifest['files']:
        name=entry['path']
        if not source_allowed(name):raise ValueError('源码清单包含禁止发布的文件')
        add('source/'+name,root/name,True)
        content=payload['source/'+name]
        if len(content)!=entry['bytes'] or digest(content)!=entry['sha256']:raise ValueError('源码在打包前变化')
    add('source/'+MANIFEST.name,root/MANIFEST.name,True)
    for path in sorted(web.rglob('*')):
        if path.is_dir() and not path.is_symlink():continue
        name=path.relative_to(web).as_posix()
        if not source_allowed(name):raise ValueError('静态目录包含非发布文件')
        add('web/'+name,path)
    if binding:
        actual=[{'path':name[4:],'bytes':len(content),'sha256':digest(content)} for name,content in sorted(payload.items()) if name.startswith('web/')]
        if actual!=binding['web_build']['files']:raise ValueError('打包的 Web 字节与验证构建不一致')
    if sum(map(len,payload.values()))>LIMIT:raise ValueError('发布包超过大小上限')
    def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
    metadata={'format':1,'purpose':'travelagent_release','git_commit':git('rev-parse','HEAD'),
        'working_tree_dirty':bool(git('status','--porcelain')),'files':[
            {'path':name,'bytes':len(content),'sha256':digest(content)} for name,content in sorted(payload.items())]}
    if binding:
        metadata['verification']={'context_fingerprint':binding['context']['fingerprint'],'web_fingerprint':binding['web_build']['fingerprint']}
    payload['RELEASE.json']=(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n').encode()
    output.mkdir(parents=True,exist_ok=False)
    temporary=output/'release.zip.partial';archive=output/'TravelAgent.zip'
    try:
        with zipfile.ZipFile(temporary,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as zipped:
            for name,content in sorted(payload.items()):
                info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.create_system=3
                info.external_attr=(stat.S_IFREG|0o644)<<16;info.compress_type=zipfile.ZIP_DEFLATED
                zipped.writestr(info,content,compresslevel=9)
        verify_archive(temporary)
        # A pre-existing archive is never replaced, even if another process races.
        os.link(temporary,archive);temporary.unlink()
        with (output/'SHA256SUMS').open('x',encoding='ascii') as stream:
            stream.write(digest(archive.read_bytes())+'  TravelAgent.zip\n')
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {'archive':str(archive),'source_files':len(manifest['files'])+1,'web_files':sum(n.startswith('web/') for n in payload),
            'sha256':digest(archive.read_bytes()),'working_tree_dirty':metadata['working_tree_dirty']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    build=commands.add_parser('build');build.add_argument('--output',type=Path,required=True)
    build.add_argument('--web-dist',type=Path,default=ROOT/'apps/web/dist')
    build.add_argument('--credentials-env',type=Path,default=ROOT/'backend/.env')
    verify=commands.add_parser('verify');verify.add_argument('archive',type=Path)
    args=parser.parse_args()
    try:
        if args.command=='build':print(json.dumps(build_release(args.output,args.web_dist,args.credentials_env),ensure_ascii=False))
        else:
            value=verify_archive(args.archive);print(f"发布包校验通过：{len(value['files'])} 个文件；SHA-256 清单不代替来源签名。")
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,subprocess.CalledProcessError):
        parser.exit(1,'发布包操作失败：请检查源码清单、输出路径、构建和凭证边界；未覆盖已有发布包。\n')


if __name__=='__main__':main()
