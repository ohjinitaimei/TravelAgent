"""Serialized verified snapshots and explicit retention, reusing travel.backup."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from travel.backup import create_snapshot, verify_snapshot

NAME=re.compile(r'^snapshot-\d{8}T\d{12}Z-[0-9a-f]{8}$')
FILES={'snapshot.sqlite3','manifest.json','managed.json'}
PURPOSE='travelagent_scheduled_backup'


def managed(root):
    valid=[];skipped=0
    for folder in root.iterdir():
        if folder.name=='.backup.lock':continue
        try:
            if (not NAME.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir()
                or folder.resolve().parent!=root or {p.name for p in folder.iterdir()}!=FILES
                or any(p.is_symlink() or not p.is_file() for p in folder.iterdir())):
                skipped+=1;continue
            marker=folder/'managed.json'
            if marker.stat().st_size>4096:raise ValueError('Invalid marker')
            if json.loads(marker.read_text(encoding='utf-8'))!={'format':1,'purpose':PURPOSE,'name':folder.name}:
                raise ValueError('Not managed by this tool')
            verify_snapshot(folder)
            valid.append(folder)
        except (OSError,ValueError,sqlite3.Error):skipped+=1
    return sorted(valid,key=lambda p:p.name,reverse=True),skipped


def run_backup(source:Path,root:Path,keep=7,prune=False):
    if not isinstance(keep,int) or isinstance(keep,bool) or not 1<=keep<=365:
        raise ValueError('保留份数须为 1–365')
    if root.is_symlink():raise ValueError('备份根目录不得为符号链接')
    source,root=source.resolve(),root.resolve()
    if not source.is_file() or source.is_relative_to(root):
        raise ValueError('源库须存在且位于备份根目录之外')
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if os.name!='nt' and root.stat().st_mode & 0o077:
        raise ValueError('备份根目录权限须为 0700')
    lock=root/'.backup.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump({'purpose':PURPOSE,'pid':os.getpid()},stream)
        name='snapshot-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid4().hex[:8]
        folder=root/name
        create_snapshot(source,folder)
        verify_snapshot(folder)
        with (folder/'managed.json').open('x',encoding='utf-8') as stream:
            json.dump({'format':1,'purpose':PURPOSE,'name':name},stream)
        valid,skipped=managed(root)
        if folder not in valid:raise ValueError('新备份未通过校验，不执行保留清理')
        # Always keep this run, even if the host clock moved backwards.
        ordered=[folder]+[p for p in valid if p!=folder]
        eligible=ordered[keep:];removed=0
        if prune:
            for old in eligible:
                # Revalidate immediately before deleting only the three owned files.
                current,_=managed(root)
                if old not in current or old.resolve().parent!=root or old.is_symlink():
                    raise ValueError('旧备份在清理前变化，已停止清理')
                for filename in ('managed.json','snapshot.sqlite3','manifest.json'):
                    (old/filename).unlink()
                old.rmdir();removed+=1
        return {'created':name,'verified':True,'retention_enabled':prune,'keep':keep,
                'eligible':len(eligible),'removed':removed,'retained':len(valid)-removed,'skipped':skipped}
    finally:
        lock.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--keep',type=int,default=7)
    parser.add_argument('--prune',action='store_true',help='显式删除超过保留份数、由本工具创建且完整校验的旧快照')
    args=parser.parse_args()
    try:result=run_backup(args.db,args.root,args.keep,args.prune)
    except (OSError,ValueError,sqlite3.Error,TimeoutError):
        parser.exit(1,'定时备份失败：请检查源库、备份权限或独占锁；未输出业务记录，未自动移除锁或覆盖源库。\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
