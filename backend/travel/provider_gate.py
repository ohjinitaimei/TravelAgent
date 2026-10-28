"""Bounded, process-shared admission for Amap Web calls; never stores facts/keys.

Only one upcoming interval is recorded. Killing a waiting worker cannot leave
reservations for the rest of its plan. No DB lock is held during sleep or HTTP.
"""
from contextlib import closing
import math
import os
from pathlib import Path
import sqlite3
import time


SETTINGS = ('TRAVEL_AMAP_RATE_DB_PATH', 'TRAVEL_AMAP_MIN_INTERVAL_SECONDS',
            'TRAVEL_AMAP_MAX_WAIT_SECONDS', 'TRAVEL_AMAP_COOLDOWN_SECONDS')


def rate_path():
    configured = os.getenv('TRAVEL_AMAP_RATE_DB_PATH')
    database = os.getenv('TRAVEL_DB_PATH')
    return Path(configured).resolve() if configured else (
        Path(database).resolve().parent if database else Path(__file__).resolve().parents[1] / 'data'
    ) / 'amap-rate.sqlite3'


class GateFailure(Exception):
    def __init__(self, code, message, status=503, retry_after=None):
        super().__init__(message)
        self.code, self.status, self.retry_after = code, status, retry_after


class ProviderGate:
    def __init__(self, path, interval=1.0, max_wait=3.0, cooldown=5.0):
        if any(not math.isfinite(v) or not low <= v <= high for v, low, high in
               ((interval, .05, 5), (max_wait, .1, 5), (cooldown, 1, 60))):
            raise ValueError('Invalid provider pacing limits')
        self.path, self.interval, self.max_wait, self.cooldown = Path(path), interval, max_wait, cooldown

    @classmethod
    def from_env(cls):
        try:
            if os.getenv('TRAVEL_DB_PATH') and rate_path() == Path(os.environ['TRAVEL_DB_PATH']).resolve():
                raise ValueError('Pacing state must have its own file')
            return cls(rate_path(), float(os.getenv(SETTINGS[1], '1')), float(os.getenv(SETTINGS[2], '3')),
                       float(os.getenv(SETTINGS[3], '5')))
        except (ValueError, TypeError, OSError):
            raise GateFailure('invalid_provider_gate_config', '高德请求节流配置无效，请检查服务端配置') from None

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=.1, isolation_level=None)
        try:
            connection.execute('CREATE TABLE IF NOT EXISTS pacing (id INTEGER PRIMARY KEY CHECK(id=1), next_at REAL NOT NULL, cooldown_until REAL NOT NULL)')
        except BaseException:
            connection.close()
            raise
        return connection

    def acquire(self):
        deadline = time.monotonic() + self.max_wait
        while True:
            delay = .025
            admission_deadline = None
            try:
                with closing(self._connect()) as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    row = connection.execute('SELECT next_at,cooldown_until FROM pacing WHERE id=1').fetchone()
                    now = time.time()
                    next_at, cooldown = row or (0, 0)
                    if cooldown > now:
                        raise GateFailure('provider_rate_limited', '高德请求正在冷却，请稍后手动重试', 429, min(300, math.ceil(cooldown-now)))
                    delay = next_at - now
                    if delay <= 0:
                        if time.monotonic() >= deadline:
                            raise GateFailure('provider_busy', '数据请求正在排队，请稍后手动重试', 429, 1)
                        admission_deadline = min(deadline,time.monotonic()+self.interval)
                        connection.execute('INSERT OR REPLACE INTO pacing VALUES (1,?,?)', (now+self.interval, cooldown))
                        connection.commit()
                    else:
                        connection.commit()
                if admission_deadline is not None:
                    # Commit/close can stall after the slot was recorded. Never
                    # release a stale slot into HTTP or replay it automatically.
                    if time.monotonic() >= admission_deadline:
                        raise GateFailure('provider_busy', '数据请求准入已过期，请稍后手动重试', 429, 1)
                    return
            except (OSError, sqlite3.Error) as error:
                if not isinstance(error, sqlite3.Error) or getattr(error, 'sqlite_errorcode', 0) & 255 not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                    raise GateFailure('provider_gate_unavailable', '高德请求调度暂不可用，请稍后重试') from None
            remaining = deadline - time.monotonic()
            if remaining <= 0 or delay > remaining:
                raise GateFailure('provider_busy', '数据请求正在排队，请稍后手动重试', 429, max(1, math.ceil(delay)))
            time.sleep(min(.05, max(.005, delay), remaining))

    def rejected(self):
        try:
            with closing(self._connect()) as connection:
                connection.execute('BEGIN IMMEDIATE')
                row = connection.execute('SELECT next_at,cooldown_until FROM pacing WHERE id=1').fetchone()
                next_at, previous = row or (0, 0)
                until = max(previous, time.time()+self.cooldown)
                connection.execute('INSERT OR REPLACE INTO pacing VALUES (1,?,?)', (next_at, until))
                connection.commit()
                return min(300, max(1, math.ceil(until-time.time())))
        except (OSError, sqlite3.Error):
            raise GateFailure('provider_gate_unavailable', '高德请求调度暂不可用，请稍后重试') from None
