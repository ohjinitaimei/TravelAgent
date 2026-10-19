"""Operator-only WAL-aware snapshots and non-overwriting offline recovery."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from time import monotonic

from travel.schemas import Draft, Error, Event, Itinerary, Task, now

TABLES = {
    'tasks': {'id', 'data'}, 'events': {'task_id', 'seq', 'data'},
    'itineraries': {'id', 'data'}, 'drafts': {'id', 'data'},
    'task_requests': {'task_id', 'data'},
    'submission_keys': {'key', 'fingerprint', 'task_id'},
    'resource_owners': {'kind', 'resource_id', 'owner_id'},
    'user_submissions': {'owner_id', 'key', 'fingerprint', 'task_id'},
    'auth_users': {'id', 'username', 'password_hash', 'disabled'},
    'auth_sessions': {'digest', 'user_id', 'expires_at', 'last_seen'},
    'auth_attempts': {'key', 'started', 'count'},
}


def read_only(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inspect_database(db):
    """Validate before Store migrations can fill in legacy local ownership."""
    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('数据库完整性校验失败')
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, columns in TABLES.items():
        if table not in tables or not columns <= {row[1] for row in db.execute(f'PRAGMA table_info({table})')}:
            raise ValueError('备份不包含当前版本所需的数据结构')
    owners = {(kind, identifier): owner for kind, identifier, owner in db.execute('SELECT kind,resource_id,owner_id FROM resource_owners')}
    users = {row[0] for row in db.execute('SELECT id FROM auth_users')}
    if any(not owner or owner != 'local' and owner not in users for owner in owners.values()):
        raise ValueError('资源归属账号缺失')
    records = {}
    for kind, table, model in [('task', 'tasks', Task), ('draft', 'drafts', Draft), ('itinerary', 'itineraries', Itinerary)]:
        records[kind] = {}
        for identifier, data in db.execute(f'SELECT id,data FROM {table}'):
            record = model.model_validate_json(data)
            if record.id != identifier or (kind, identifier) not in owners:
                raise ValueError('业务记录或资源归属缺失')
            records[kind][identifier] = record
    if set(owners) != {(kind, identifier) for kind, items in records.items() for identifier in items}:
        raise ValueError('存在失效资源归属')
    for identifier, task in records['task'].items():
        for kind, result in [('draft', task.draft_id), ('itinerary', task.itinerary_id), ('task', task.retry_of)]:
            if result and (result not in records[kind] or owners[kind, result] != owners['task', identifier]):
                raise ValueError('任务引用或归属不一致')
    for identifier, trip in records['itinerary'].items():
        if trip.parent_id and owners.get(('itinerary', trip.parent_id)) != owners['itinerary', identifier]:
            raise ValueError('行程版本归属不一致')
    for owner, identifier in db.execute('SELECT owner_id,task_id FROM user_submissions'):
        if owners.get(('task', identifier)) != owner:
            raise ValueError('提交收据归属不一致')
    for identifier, data in db.execute('SELECT task_id,data FROM task_requests'):
        if identifier not in records['task'] or not isinstance(json.loads(data), dict):
            raise ValueError('任务请求快照无效')
    for identifier, seq, data in db.execute('SELECT task_id,seq,data FROM events'):
        if identifier not in records['task'] or Event.model_validate_json(data).id != seq:
            raise ValueError('任务事件引用无效')
    return {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in TABLES}


def create_snapshot(source: Path, output: Path):
    source, output = source.resolve(), output.resolve()
    if not source.is_file():
        raise ValueError('源数据库不存在')
    # A fresh directory prevents replacing an earlier snapshot or its manifest.
    output.mkdir(parents=True, exist_ok=False)
    snapshot, manifest = output / 'snapshot.sqlite3', output / 'manifest.json'
    try:
        deadline = monotonic() + 60

        def progress(*_):
            if monotonic() > deadline:
                raise TimeoutError('备份超过 60 秒，请在低峰时重试')

        with closing(read_only(source)) as src, closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst, pages=256, progress=progress, sleep=.05)
            dst.execute('PRAGMA journal_mode=DELETE')
            counts = inspect_database(dst)
        info = {'format': 1, 'created_at': now(), 'sha256': checksum(snapshot),
                'size_bytes': snapshot.stat().st_size, 'rows': counts}
        # Completion marker is written only after the database is closed/verified.
        with manifest.open('x', encoding='utf-8') as stream:
            json.dump(info, stream, indent=2)
        return info
    except Exception:
        # Only files in the new directory belong to this operation.
        for name in ('manifest.json', 'snapshot.sqlite3', 'snapshot.sqlite3-journal', 'snapshot.sqlite3-wal', 'snapshot.sqlite3-shm'):
            (output / name).unlink(missing_ok=True)
        output.rmdir()
        raise


def verify_snapshot(folder: Path):
    folder = folder.resolve()
    manifest, snapshot = folder / 'manifest.json', folder / 'snapshot.sqlite3'
    if not manifest.is_file() or manifest.stat().st_size > 65536:
        raise ValueError('备份完成标记缺失或无效')
    info = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(info, dict) or info.get('format') != 1:
        raise ValueError('不支持的备份格式')
    if snapshot.stat().st_size != info.get('size_bytes') or checksum(snapshot) != info.get('sha256'):
        raise ValueError('备份校验和不匹配')
    with closing(read_only(snapshot)) as db:
        if inspect_database(db) != info.get('rows'):
            raise ValueError('备份记录数量不匹配')
    return info


def restore_snapshot(folder: Path, destination: Path):
    """Write a NEW DB only. CLI requires the operator to stop the API first."""
    info = verify_snapshot(folder)
    destination = destination.resolve()
    if any(Path(str(destination) + suffix).exists() for suffix in ('', '-wal', '-shm', '-journal')):
        raise FileExistsError('恢复目标或伴随文件已存在，请选择全新的数据库路径')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.travel-restore-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'restored.sqlite3'
        shutil.copyfile(folder.resolve() / 'snapshot.sqlite3', staged)
        if checksum(staged) != info['sha256']:
            raise ValueError('备份在恢复期间发生变化')
        with closing(sqlite3.connect(staged)) as db:
            inspect_database(db)
            with db:
                # A historical bearer/cookie must never become valid again.
                db.execute('DELETE FROM auth_sessions')
                interrupted = 0
                for identifier, data in db.execute('SELECT id,data FROM tasks').fetchall():
                    task = Task.model_validate_json(data)
                    if task.status not in {'queued', 'running'}:
                        continue
                    interrupted += 1
                    task.status, task.updated_at = 'failed', now()
                    task.error = Error(code='backup_restored', message='任务在备份恢复时中断，可核对条件后重试', retryable=True)
                    task.retry_available = db.execute('SELECT 1 FROM task_requests WHERE task_id=?', (identifier,)).fetchone() is not None
                    db.execute('UPDATE tasks SET data=? WHERE id=?', (task.model_dump_json(), identifier))
                    seq = db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE task_id=?', (identifier,)).fetchone()[0]
                    event = Event(id=seq, stage='failed', message=task.error.message)
                    db.execute('INSERT INTO events VALUES (?,?,?)', (identifier, seq, event.model_dump_json()))
            inspect_database(db)
        # Atomic, no-replace publication on NTFS/POSIX. Never overwrite a live DB.
        os.link(staged, destination)
    return {'interrupted_tasks': interrupted, 'sessions_revoked': info['rows']['auth_sessions']}


def main():
    from dotenv import load_dotenv
    backend = Path(__file__).resolve().parents[1]
    load_dotenv(backend / '.env')
    parser = argparse.ArgumentParser(description='本机数据库备份、校验与恢复；不提供 HTTP 下载接口。')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('--db', type=Path, default=Path(os.getenv('TRAVEL_DB_PATH', str(backend / 'data/travel.sqlite3'))))
    create.add_argument('--output', type=Path, required=True, help='尚不存在的备份目录')
    verify = commands.add_parser('verify')
    verify.add_argument('folder', type=Path)
    restore = commands.add_parser('restore')
    restore.add_argument('folder', type=Path)
    restore.add_argument('--db', type=Path, required=True, help='全新恢复目标；不会覆盖原数据库')
    restore.add_argument('--service-stopped', action='store_true')
    args = parser.parse_args()
    if args.command == 'restore' and not args.service_stopped:
        parser.error('请先停止 API，再传入 --service-stopped；恢复不会自动启动服务')
    try:
        if args.command == 'create':
            create_snapshot(args.db, args.output)
        elif args.command == 'verify':
            verify_snapshot(args.folder)
        else:
            restore_snapshot(args.folder, args.db)
        print('操作完成；完整性和归属检查通过。恢复后需重新登录。')
    except (OSError, ValueError, sqlite3.Error, TimeoutError):
        parser.exit(1, '操作失败：请检查路径、备份完整性和版本兼容性；原数据库未被覆盖。\n')


if __name__ == '__main__':
    main()
