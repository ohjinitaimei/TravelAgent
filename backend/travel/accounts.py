"""Operator-only account management: python -m travel.accounts <command> <username>."""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from travel.auth import AuthService, username
from travel.store import Store


def claim_local(store,name):
    with store.lock,store.db:
        user=store.db.execute('SELECT id FROM auth_users WHERE username=? AND disabled=0',(username(name),)).fetchone()
        if not user: raise ValueError('可用账号不存在')
        rows=store.db.execute("SELECT t.data FROM tasks t JOIN resource_owners o ON o.kind='task' AND o.resource_id=t.id WHERE o.owner_id='local'").fetchall()
        if any(json.loads(row[0])['status'] in {'queued','running'} for row in rows):
            raise ValueError('仍有本地任务未结束，请先停止服务并处理任务记录')
        conflict=store.db.execute("SELECT 1 FROM user_submissions a JOIN user_submissions b ON a.key=b.key WHERE a.owner_id='local' AND b.owner_id=? LIMIT 1",(user[0],)).fetchone()
        if conflict: raise ValueError('提交标识存在冲突，未更改任何归属')
        store.db.execute("UPDATE resource_owners SET owner_id=? WHERE owner_id='local'",(user[0],))
        store.db.execute("UPDATE user_submissions SET owner_id=? WHERE owner_id='local'",(user[0],))


def main():
    backend=Path(__file__).resolve().parents[1]
    load_dotenv(backend/'.env')
    parser=argparse.ArgumentParser(description='本机管理员操作；密码只通过隐藏提示输入，不提供默认账号。')
    parser.add_argument('command',choices=['create','reset-password','disable','enable','claim-local'])
    parser.add_argument('username')
    parser.add_argument('--db',type=Path,default=Path(os.getenv('TRAVEL_DB_PATH',str(backend/'data/travel.sqlite3'))))
    parser.add_argument('--service-stopped',action='store_true',help='claim-local 前确认服务已停止并已备份数据库')
    args=parser.parse_args()
    if args.command=='claim-local' and not args.service_stopped:
        parser.error('claim-local 需先停止服务、备份数据库并显式传入 --service-stopped')
    password=None
    if args.command in {'create','reset-password'}:
        password=getpass('密码（15–128 个字符）：')
        if password!=getpass('再次输入密码：'): parser.error('两次密码不一致')
    store=Store(args.db.resolve())
    try:
        auth=AuthService(store)
        if args.command=='create': auth.create_user(args.username,password)
        elif args.command=='reset-password': auth.reset_password(args.username,password)
        elif args.command=='disable': auth.disable_user(args.username)
        elif args.command=='enable': auth.enable_user(args.username)
        else: claim_local(store,args.username)
        print('操作完成。密码、Token 和个人行程不会显示在输出中。')
    except ValueError as error: parser.exit(1,str(error)+'\n')
    finally: store.close()


if __name__=='__main__': main()
