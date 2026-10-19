"""Single-instance admission control; accepted business requests persist their quota."""
from contextlib import contextmanager
import math
import os
from threading import BoundedSemaphore, Lock
from time import time

from travel.provider import TravelFailure


def positive_setting(name, default, maximum):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f'{name} 必须是整数') from None
    if not 1 <= value <= maximum:
        raise ValueError(f'{name} 必须在 1–{maximum} 之间')
    return value


def rejected(code, message, seconds):
    seconds = max(1, math.ceil(seconds))
    error = TravelFailure(code, f'{message}，请在 {seconds} 秒后重试', True, 429)
    error.retry_after = seconds
    return error


class BusinessLimits:
    def __init__(self, store, clock=time):
        self.store, self.clock = store, clock
        self.task_limit = positive_setting('TRAVEL_LIMIT_TASKS', 20, 10000)
        self.global_tasks = positive_setting('TRAVEL_LIMIT_TASKS_GLOBAL', 60, 100000)
        self.active_tasks = positive_setting('TRAVEL_LIMIT_ACTIVE_TASKS', 3, 10)
        self.tool_limit = positive_setting('TRAVEL_LIMIT_TOOLS', 60, 10000)
        self.global_tools = positive_setting('TRAVEL_LIMIT_TOOLS_GLOBAL', 180, 100000)
        self.check_limit = positive_setting('TRAVEL_LIMIT_TOOL_CHECKS', 3, 1000)
        self.tool_slots = BoundedSemaphore(positive_setting('TRAVEL_TOOL_CONCURRENCY', 4, 32))
        self.stream_limit = positive_setting('TRAVEL_LIMIT_STREAMS', 3, 32)
        self.stream_total = positive_setting('TRAVEL_LIMIT_STREAMS_GLOBAL', 30, 256)
        self.streams, self.stream_lock = {}, Lock()
        with store.lock, store.db:
            store.db.execute('''CREATE TABLE IF NOT EXISTS business_limits (
                scope TEXT, subject TEXT, started REAL NOT NULL, count INTEGER NOT NULL,
                PRIMARY KEY(scope,subject))''')

    def _charge(self, entries, window, code):
        """Caller holds the store transaction: all buckets charge together or none."""
        current = self.clock()
        updates = []
        for scope, subject, limit in entries:
            row = self.store.db.execute('SELECT started,count FROM business_limits WHERE scope=? AND subject=?', (scope, subject)).fetchone()
            started, count = row if row and current < row[0] + window else (current, 0)
            if count >= limit:
                raise rejected(code, '请求次数达到服务限额', started + window - current)
            updates.append((scope, subject, started, count + 1))
        self.store.db.execute('DELETE FROM business_limits WHERE started < ?', (current - 300,))
        self.store.db.executemany('INSERT OR REPLACE INTO business_limits VALUES (?,?,?,?)', updates)

    def admit_task(self, owner):
        # Runs inside register_task after receipt lookup, before any task insert.
        rows = self.store.db.execute("SELECT t.data FROM tasks t JOIN resource_owners o ON o.kind='task' AND o.resource_id=t.id WHERE o.owner_id=?", (owner,)).fetchall()
        import json
        if sum(json.loads(row[0])['status'] in {'queued', 'running'} for row in rows) >= self.active_tasks:
            raise rejected('task_concurrency_limited', '当前账号已有多个未结束任务，可查询或取消后再提交', 2)
        self._charge([('tasks', owner, self.task_limit), ('tasks-global', '*', self.global_tasks)], 300, 'task_rate_limited')

    @contextmanager
    def tool(self, owner, *, check=False):
        if not self.tool_slots.acquire(blocking=False):
            raise rejected('tool_busy', '工具服务正在处理其他请求', 2)
        try:
            entries = [('tools', owner, self.tool_limit), ('tools-global', '*', self.global_tools)]
            if check:
                entries.append(('tool-check', owner, self.check_limit))
            with self.store.lock, self.store.db:
                self._charge(entries, 60, 'tool_rate_limited')
            # Failures still consumed an admitted tool request; no automatic retry.
            yield
        finally:
            self.tool_slots.release()

    def acquire_stream(self, owner):
        with self.stream_lock:
            if self.streams.get(owner, 0) >= self.stream_limit or sum(self.streams.values()) >= self.stream_total:
                raise rejected('stream_limit', '事件连接数达到服务限额，请使用状态轮询', 2)
            self.streams[owner] = self.streams.get(owner, 0) + 1
        released = False

        def release():
            nonlocal released
            with self.stream_lock:
                if released:
                    return
                released = True
                remaining = self.streams[owner] - 1
                if remaining:
                    self.streams[owner] = remaining
                else:
                    del self.streams[owner]
        return release
